"""Motor de Atividades de Campo.

Regra de negócio da OZ: o cliente aprova o orçamento do diagnóstico ANTES da ida ao terreno.
Por isso, antes da proposta o sistema prevê tudo o que pode ser necessário para diagnosticar:

- BASE: atividade normalmente necessária;
- CONDICIONAL: pode ser necessária consoante o que se encontrar; entra no âmbito e no valor total
  da proposta e executa-se quando o gatilho técnico ocorre, sem nova aprovação do cliente;
- consequências (reposições, inspeção interna, fecho de aberturas) vêm das dependências.

Os preços vêm SEMPRE de services.selling_price (definido pelo engenheiro). A IA nunca define preços.
A solução de reparação NÃO faz parte da proposta: fica como hipótese interna
(proposal_solution_hypotheses) para o engenheiro comparar com o diagnóstico de campo.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.supabase_rest import rest

BASE, CONDITIONAL = "BASE", "CONDITIONAL"
STRONG_MATCH = 60          # aderência (%) a partir da qual um ensaio da base técnica é atividade BASE
FIELD_TEST_CATEGORIES = {"NDT", "MONITORING"}
REPORT_SERVICE_ID = "REL_ENS"
ELECTRICAL_SERVICE_KEYWORDS = (
    ("ELEC_INSPECT", ("inspecao", "inspeccao", "inspecionar")),
    ("ELEC_CONTINUITY", ("continuidade",)),
    ("ELEC_INSULATION", ("isolamento",)),
    ("ELEC_LOAD", ("carga", "sobrecarga")),
    ("ELEC_REPORT", ("relatorio", "recomendacoes")),
)
DEFAULT_EXCLUSIONS = (
    "Execução das obras de reparação ou reforço.",
    "Projeto de reparação, de reforço ou de escoramento.",
    "Ensaios e trabalhos não indicados nesta proposta.",
)
_PRICE_NOTE = re.compile(r"\s*Preço a definir pelo engenheiro\.?", re.I)


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def client_text(value: Any) -> str:
    """Texto do catálogo adequado à proposta (sem notas internas de preço)."""
    return _PRICE_NOTE.sub("", str(value or "")).strip()


def _group(pathology_code: str) -> str:
    parts = str(pathology_code).split("-")
    return parts[1] if len(parts) >= 3 else ""


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


class _Plan:
    def __init__(self, catalog: dict[str, dict[str, Any]]):
        self.catalog = catalog
        self.activities: dict[str, dict[str, Any]] = {}
        self.unmapped: list[dict[str, str]] = []

    def add(self, service_id: str, activity_class: str, *, condition: str | None = None, reason: str = "",
            quantity: float = 1, quantity_rule: str = "FIXED", parent: str | None = None) -> bool:
        if service_id not in self.catalog:
            return False
        current = self.activities.get(service_id)
        if current is None:
            self.activities[service_id] = {
                "service_id": service_id, "activity_class": activity_class,
                "conditions": [condition] if condition else [], "reasons": [reason] if reason else [],
                "quantity": quantity, "quantity_rule": quantity_rule, "parent": parent,
            }
            return True
        if activity_class == BASE:
            current["activity_class"] = BASE
        if condition and condition not in current["conditions"]:
            current["conditions"].append(condition)
        if reason and reason not in current["reasons"]:
            current["reasons"].append(reason)
        current["quantity"] = max(float(current["quantity"]), float(quantity))
        return False


def _rule_matches(rule: dict[str, Any], *, groups: set[str], pathology_codes: set[str], corpus: str,
                  storeys: int, electrical_only: bool) -> bool:
    kind, value = rule.get("trigger_type"), str(rule.get("trigger_value") or "")
    if kind == "ALWAYS":
        return not electrical_only
    if kind == "PATHOLOGY_GROUP":
        return value in groups
    if kind == "PATHOLOGY":
        return value in pathology_codes
    if kind == "TERM":
        return fold(value) in corpus
    if kind == "MIN_STOREYS":
        return storeys >= _to_int(value) > 0
    return False


def plan_field_activities(*, fields: dict[str, Any], raw_text: str, candidates: list[dict[str, Any]],
                          rules: list[dict[str, Any]], dependencies: list[dict[str, Any]],
                          catalog: dict[str, dict[str, Any]],
                          services_by_test: dict[str, list[str]]) -> dict[str, Any]:
    """Função pura (sem base de dados): decide atividades, hipóteses de solução e alertas."""
    plan = _Plan(catalog)
    candidates = [c for c in candidates if c.get("code")]
    corpus = fold(" ".join([
        raw_text or "", str(fields.get("objective") or ""), str(fields.get("problem_summary") or ""),
        " ".join(fields.get("symptom_locations") or []), " ".join(fields.get("requested_services") or []),
        " ".join(fields.get("categories") or []),
    ]))
    groups = {_group(c["code"]) for c in candidates} - {""}
    pathology_codes = {str(c["code"]) for c in candidates}
    storeys = _to_int(fields.get("storey_count"))
    electrical_only = "eletric" in corpus and not candidates

    # 0) Serviços elétricos pedidos explicitamente pelo cliente
    requested = fold(" ".join(fields.get("requested_services") or []))
    if "eletric" in corpus:
        for service_id, words in ELECTRICAL_SERVICE_KEYWORDS:
            if any(word in requested for word in words):
                plan.add(service_id, BASE, reason="Pedido pelo cliente")

    # 1) Regras determinísticas da OZ (BASE e CONDICIONAL)
    for rule in sorted((r for r in rules if r.get("active", True)), key=lambda r: (r.get("priority") or 100, r["code"])):
        if not _rule_matches(rule, groups=groups, pathology_codes=pathology_codes, corpus=corpus,
                             storeys=storeys, electrical_only=electrical_only):
            continue
        if rule["service_id"] not in catalog:
            plan.unmapped.append({"kind": "regra", "code": rule["code"], "name": rule["service_id"], "pathology": ""})
            continue
        plan.add(rule["service_id"], rule["activity_class"], condition=rule.get("trigger_condition"),
                 reason=f"Regra {rule['code']}", quantity=float(rule.get("quantity_value") or 1),
                 quantity_rule=rule.get("quantity_rule") or "FIXED")

    # 2) Ensaios sugeridos pela base técnica (RAG): apoiam a interpretação, as regras decidem a composição
    for candidate in candidates:
        match = int(candidate.get("match_percent") or 0)
        for test in candidate.get("tests", []):
            code = str(test.get("code"))
            service_ids = [sid for sid in services_by_test.get(code, []) if sid in catalog]
            if not service_ids:
                plan.unmapped.append({"kind": "ensaio", "code": code, "name": str(test.get("name")),
                                      "pathology": str(candidate["code"]), "match": str(match)})
                continue
            for service_id in service_ids:
                strong = match >= STRONG_MATCH
                plan.add(service_id, BASE if strong else CONDITIONAL,
                         condition=None if strong else f"a vistoria confirmar «{candidate.get('name')}»",
                         reason=f"Ensaio {code} — {test.get('name')} (patologia {candidate['code']}, aderência {match}%)")

    # 3) Relatório dos ensaios/monitorização
    if REPORT_SERVICE_ID in catalog and any(
            catalog[sid].get("category") in FIELD_TEST_CATEGORIES for sid in plan.activities):
        plan.add(REPORT_SERVICE_ID, BASE, reason="Relatório dos ensaios e da monitorização propostos")

    # 4) Dependências: consequências (reposição, inspeção interna, fecho) até estabilizar
    followups: dict[str, list[dict[str, Any]]] = {}
    for dep in dependencies:
        followups.setdefault(dep["service_id"], []).append(dep)
    changed = True
    guard = 0
    while changed and guard < 20:
        changed, guard = False, guard + 1
        for service_id, activity in list(plan.activities.items()):
            for dep in followups.get(service_id, []):
                target = dep["followup_service_id"]
                if target not in catalog:
                    continue
                created = plan.add(
                    target, activity["activity_class"],
                    condition=activity["conditions"][0] if activity["conditions"] else None,
                    reason=f"Consequência de {catalog[service_id]['name']} ({dep.get('relation')})",
                    quantity=float(activity["quantity"]) * float(dep.get("quantity_ratio") or 1), parent=service_id)
                changed = changed or created

    # 5) Hipóteses de solução: INFORMAÇÃO INTERNA, não entram na proposta
    hypotheses: list[dict[str, str]] = []
    for candidate in candidates:
        evidence = " | ".join(candidate.get("evidence") or [])[:600]
        for solution in candidate.get("solutions", []):
            hypotheses.append({"pathology_code": str(candidate["code"]), "solution_code": str(solution.get("code")),
                               "solution_name": str(solution.get("name")), "evidence": evidence})

    activities = sorted(plan.activities.values(),
                        key=lambda a: (0 if a["activity_class"] == BASE else 1, a["service_id"]))
    return {"activities": activities, "hypotheses": hypotheses, "unmapped": plan.unmapped,
            "exclusions": list(DEFAULT_EXCLUSIONS), "flags": _validate(plan, candidates, corpus, activities)}


def _validate(plan: _Plan, candidates: list[dict[str, Any]], corpus: str,
              activities: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Validação anti-falhas (fase 1: só calcula alertas; o bloqueio da aprovação vem na fase 2)."""
    flags: list[dict[str, str]] = []
    if not any(a["activity_class"] == BASE for a in activities):
        flags.append({"code": "NO_BASE_ACTIVITY", "severity": "CRITICAL",
                      "message": "Nenhuma atividade base foi identificada."})
    for item in plan.unmapped:
        strong = int(item.get("match") or 0) >= STRONG_MATCH
        flags.append({"code": "UNMAPPED_" + item["kind"].upper(), "severity": "CRITICAL" if strong else "WARNING",
                      "message": f"{item['kind'].capitalize()} {item['code']} {item['name']} sem serviço no catálogo: "
                                 "não ficou orçamentado."})
    has_reinstatement = any(plan.catalog[a["service_id"]].get("category") == "REINSTATEMENT" for a in activities)
    for activity in activities:
        service = plan.catalog[activity["service_id"]]
        if service.get("category") == "INTRUSIVE" and not has_reinstatement:
            flags.append({"code": "INTRUSIVE_WITHOUT_REINSTATEMENT", "severity": "CRITICAL",
                          "message": f"{service['name']} não tem reposição prevista."})
    unpriced = [plan.catalog[a["service_id"]]["name"] for a in activities
                if float(plan.catalog[a["service_id"]].get("selling_price") or 0) <= 0]
    if unpriced:
        flags.append({"code": "UNPRICED_ACTIVITIES", "severity": "WARNING",
                      "message": f"{len(unpriced)} atividade(s) sem preço no catálogo: " + "; ".join(unpriced[:8])})
    if not candidates and any(word in corpus for word in ("fissura", "humidade", "infiltracao", "armadura", "fuga")):
        flags.append({"code": "NO_PATHOLOGY_MATCH", "severity": "WARNING",
                      "message": "Nenhuma patologia reconhecida: só atividades base e regras gerais."})
    if any(word in corpus for word in ("colapso", "risco de queda", "desabamento", "derrocada")):
        flags.append({"code": "SAFETY_RISK", "severity": "WARNING",
                      "message": "O pedido refere colapso/risco de queda: confirmar medidas de segurança imediatas "
                                 "(fora do âmbito desta proposta)."})
    return flags


async def load_reference_data(token: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    rules = await rest(token, "diagnostic_activity_rules", params={"active": "eq.true", "select": "*", "limit": "500"})
    deps = await rest(token, "diagnostic_activity_dependencies", params={"select": "*", "limit": "500"})
    catalog_rows = await rest(token, "services", params={
        "active": "eq.true", "select": "service_id,name,unit,technical_basis,category,selling_price", "limit": "500"})
    test_codes = sorted({str(t["code"]) for c in candidates for t in c.get("tests", []) if t.get("code")})
    services_by_test: dict[str, list[str]] = {}
    if test_codes:
        joined = ",".join(test_codes)
        for row in await rest(token, "kb_test_services", params={
                "test_code": f"in.({joined})", "select": "test_code,service_id", "limit": "1000"}):
            services_by_test.setdefault(row["test_code"], []).append(row["service_id"])
        for row in await rest(token, "kb_tests", params={
                "code": f"in.({joined})", "select": "code,service_id", "limit": "500"}):
            if row.get("service_id") and row["code"] not in services_by_test:
                services_by_test[row["code"]] = [row["service_id"]]
    return {"rules": rules or [], "dependencies": deps or [], "catalog": {r["service_id"]: r for r in catalog_rows},
            "services_by_test": services_by_test}


def _item_rows(plan: dict[str, Any], catalog: dict[str, dict[str, Any]], owner_id: str, proposal_id: str,
               existing_service_ids: set[str], first_position: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for activity in plan["activities"]:
        service = catalog[activity["service_id"]]
        if activity["service_id"] in existing_service_ids:
            continue
        price = float(service.get("selling_price") or 0)
        basis = client_text(service.get("technical_basis"))
        condition = "; ".join(activity["conditions"]) or None
        if activity["activity_class"] == CONDITIONAL:
            prefix = (f"Atividade condicional, incluída neste orçamento e executada se {condition}."
                      if condition else "Atividade condicional, incluída neste orçamento.")
            basis = f"{prefix} {basis}".strip()
        rows.append({
            "owner_id": owner_id, "proposal_id": proposal_id, "service_id": activity["service_id"],
            "name": service["name"], "unit": service["unit"], "quantity": activity["quantity"],
            "unit_price": price, "enabled": True, "is_optional": False,
            "origin": "SUGGESTED" if price > 0 else "REQUIRES_REVIEW",
            "technical_basis": basis[:1500] or None,
            "internal_note": " | ".join(activity["reasons"])[:1500] or None,
            "activity_class": activity["activity_class"], "trigger_condition": condition,
            "quantity_rule": activity["quantity_rule"], "included_in_approved_scope": True,
            "position": first_position + len(rows),
        })
    return rows


async def run_field_activity_engine(token: str, owner_id: str, proposal_id: str, request_id: str,
                                    fields: dict[str, Any], raw_text: str,
                                    technical: dict[str, Any] | None) -> dict[str, Any]:
    """Prevê as atividades de campo e acrescenta-as à proposta. Nunca remove nem duplica linhas."""
    candidates = (technical or {}).get("confirmed") or (technical or {}).get("candidates") or []
    data = await load_reference_data(token, candidates)
    plan = plan_field_activities(fields=fields, raw_text=raw_text, candidates=candidates, **data)

    current = await rest(token, "proposal_items", params={
        "proposal_id": f"eq.{proposal_id}", "select": "service_id,position"})
    existing = {item["service_id"] for item in current if item.get("service_id")}
    next_position = max((int(item.get("position") or 0) for item in current), default=-1) + 1
    rows = _item_rows(plan, data["catalog"], owner_id, proposal_id, existing, next_position)
    created: list[dict[str, Any]] = []
    if rows:
        created = await rest(token, "proposal_items", method="POST", body=rows, prefer="return=representation") or []
        id_by_service = {row["service_id"]: row["id"] for row in created if row.get("service_id")}
        parents = {a["service_id"]: a["parent"] for a in plan["activities"] if a["parent"]}
        for service_id, parent in parents.items():
            if service_id in id_by_service and parent in {**id_by_service, **{s: "x" for s in existing}}:
                parent_id = id_by_service.get(parent)
                if parent_id:
                    await rest(token, "proposal_items", method="PATCH", params={"id": f"eq.{id_by_service[service_id]}"},
                               body={"parent_item_id": parent_id}, prefer="return=minimal")
    if plan["hypotheses"]:
        await rest(token, "proposal_solution_hypotheses", method="POST",
                   params={"on_conflict": "request_id,pathology_code,solution_code"},
                   body=[{"owner_id": owner_id, "request_id": request_id, **row} for row in plan["hypotheses"]],
                   prefer="resolution=ignore-duplicates,return=minimal")
    return {"added": [row["name"] for row in rows], "unmapped": plan["unmapped"], "flags": plan["flags"],
            "exclusions": plan["exclusions"], "hypotheses": len(plan["hypotheses"])}
