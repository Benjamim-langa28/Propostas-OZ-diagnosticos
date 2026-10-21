"""Reconstrói o âmbito de uma proposta nova a partir de propostas anteriores semelhantes.

Só usa propostas aprovadas/enviadas/aceites (rascunhos não são referência) e do mesmo material."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.proposal_library import match_request_to_prior_proposals
from app.services.field_activities import CONDITIONAL, _item_rows
from app.services.material_guard import detect_materials, request_text
from app.services.pdf_knowledge import _material_compatible
from app.supabase_rest import rest

MIN_MATCH = 35      # ignora propostas anteriores pouco parecidas (%)
MIN_SHARE = 0.5     # o serviço tem de constar em pelo menos metade (ponderada) das propostas parecidas
MAX_ADDED = 15
TRUSTED_STATUSES = ("APPROVED", "SENT", "CLIENT_REVIEW", "ACCEPTED")
CLIENT_CONDITION = "Executar se a inspeção de campo confirmar a necessidade desta atividade."


def _qty(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(int(number)) if number == int(number) else f"{number:g}"


def _none(message: str) -> dict[str, Any]:
    return {"added": [], "flags": [{"severity": "INFO", "code": "PRIOR_SUMMARY", "message": message}]}


def _in(values: list[str]) -> str:
    return "in.(" + ",".join(values) + ")"


async def add_prior_proposal_activities(token: str, proposal_id: str, request_id: str) -> dict[str, Any]:
    current = await rest(token, "proposal_requests", params={
        "id": f"eq.{request_id}", "select": "raw_text,extracted_fields", "limit": "1"})
    current = current[0] if isinstance(current, list) and current else {}
    materials = detect_materials(request_text(current.get("extracted_fields") or {}, current.get("raw_text") or ""))

    matches = await match_request_to_prior_proposals(
        request_id=request_id, user=SimpleNamespace(token=token))
    similar = [m for m in matches if m.get("source") == "generated" and m.get("id")
               and float(m.get("match_percent") or 0) >= MIN_MATCH]
    if not similar:
        return _none("Não há propostas anteriores geradas suficientemente parecidas para servir de referência.")

    props = await rest(token, "proposals", params={
        "id": _in([str(m["id"]) for m in similar]), "select": "id,status,request_id"})
    trusted = {str(r["id"]): r for r in (props if isinstance(props, list) else [])
               if r.get("status") in TRUSTED_STATUSES}
    similar = [m for m in similar if str(m["id"]) in trusted]
    if not similar:
        return _none("Não há propostas anteriores aprovadas ou enviadas parecidas; os rascunhos não são usados "
                     "como referência.")

    request_ids = sorted({str(trusted[str(m["id"])].get("request_id")) for m in similar
                          if trusted[str(m["id"])].get("request_id")})
    compatible: set[str] = set()
    if request_ids:
        req_rows = await rest(token, "proposal_requests", params={
            "id": _in(request_ids), "select": "id,raw_text,extracted_fields"})
        for r in req_rows if isinstance(req_rows, list) else []:
            text = request_text(r.get("extracted_fields") or {}, r.get("raw_text") or "")
            if _material_compatible(materials, text[:20000]):
                compatible.add(str(r["id"]))
    similar = [m for m in similar if str(trusted[str(m["id"])].get("request_id")) in compatible]
    if not similar:
        return _none("As propostas anteriores parecidas são de outro material; não foram usadas.")

    ids = [str(m["id"]) for m in similar]
    rows = await rest(token, "proposal_items", params={
        "proposal_id": _in(ids), "enabled": "eq.true",
        "select": "proposal_id,service_id,quantity", "limit": "5000"})
    rows = rows if isinstance(rows, list) else []

    weight = {str(m["id"]): float(m.get("match_percent") or 0) for m in similar}
    label = {str(m["id"]): str(m.get("proposal_no") or m.get("title") or "proposta anterior") for m in similar}
    total_weight = sum(weight.values()) or 1.0
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("service_id") or "").strip()
        pid = str(row.get("proposal_id") or "")
        if sid and pid in weight:
            found.setdefault(sid, {})[pid] = row.get("quantity")
    ranked = []
    for sid, per_proposal in found.items():
        share = sum(weight[p] for p in per_proposal) / total_weight
        if share >= MIN_SHARE:
            ranked.append((share, len(per_proposal), sid))
    ranked.sort(reverse=True)
    ranked = ranked[:MAX_ADDED]

    services = await rest(token, "services", params={
        "active": "eq.true", "select": "service_id,name,unit,technical_basis,category,selling_price",
        "limit": "5000"})
    catalog = {str(s.get("service_id") or "").strip(): s
               for s in (services if isinstance(services, list) else []) if s.get("service_id")}

    activities = []
    for _share, count, sid in ranked:
        service = catalog.get(sid)
        if not service:
            continue
        per_proposal = found[sid]
        refs = ", ".join(label[p] for p in list(per_proposal)[:4])
        quantities = ", ".join(sorted({q for q in (_qty(v) for v in per_proposal.values()) if q}))
        reason = (f"Consta em {count} de {len(similar)} propostas anteriores aprovadas semelhantes ({refs})."
                  + (f" Quantidades anteriores: {quantities}." if quantities else ""))
        activities.append({
            "service_id": sid, "name": service.get("name"), "unit": service.get("unit"),
            "quantity": 1, "activity_class": CONDITIONAL, "conditions": [CLIENT_CONDITION],
            "trigger_condition": CLIENT_CONDITION, "reasons": [reason],
            "technical_basis": service.get("technical_basis") or "",
        })

    existing = await rest(token, "proposal_items", params={
        "proposal_id": f"eq.{proposal_id}", "select": "service_id,position", "limit": "5000"})
    existing = existing if isinstance(existing, list) else []
    existing_ids = {str(r.get("service_id") or "").strip() for r in existing if r.get("service_id")}
    max_position = 0
    for row in existing:
        try:
            max_position = max(max_position, int(float(row.get("position") or 0)))
        except (TypeError, ValueError):
            pass
    new_rows = _item_rows(proposal_id, activities, catalog, existing_ids, max_position + 1)
    added: list[str] = []
    if new_rows:
        inserted = await rest(token, "proposal_items", method="POST", body=new_rows,
                              prefer="return=representation")
        if isinstance(inserted, list):
            added = [str(r.get("service_id")) for r in inserted if r.get("service_id")]

    names = [str(catalog[s].get("name")) for s in added if s in catalog][:8]
    summary = (f"Propostas anteriores aprovadas semelhantes consultadas: {len(similar)} "
               f"({', '.join(label[i] for i in ids[:4])}); {len(added)} serviço(s) acrescentado(s) a partir delas"
               + (": " + ", ".join(names) + "." if names else "."))
    return {"added": added, "flags": [{"severity": "INFO", "code": "PRIOR_SUMMARY", "message": summary}]}