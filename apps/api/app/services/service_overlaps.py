"""Serviços que se sobrepõem: só um de cada grupo fica ativo quando foram sugeridos automaticamente."""
from __future__ import annotations

from app.supabase_rest import rest

# O PRIMEIRO serviço de cada grupo é o preferido. Se houver mais do que um no orçamento,
# os seguintes (se tiverem sido sugeridos automaticamente) ficam desativados.
# CONFIRMAR COM O ENGENHEIRO e ajustar a ordem ou os grupos aqui.
OVERLAP_GROUPS = (
    ("inspeção visual", ("EST_VISUAL", "INSP_ANOM", "LEV_ANOM")),
    ("verba fixa de mobilização", ("MOB", "VERBA_LEV")),
)


async def resolve_overlaps(token: str, proposal_id: str, added_service_ids: set[str]) -> list[str]:
    rows = await rest(token, "proposal_items", params={
        "proposal_id": f"eq.{proposal_id}", "enabled": "eq.true",
        "select": "id,service_id,name,internal_note", "limit": "5000"})
    rows = rows if isinstance(rows, list) else []
    by_service: dict[str, dict] = {}
    for row in rows:
        sid = str(row.get("service_id") or "")
        if sid:
            by_service.setdefault(sid, row)
    messages: list[str] = []
    for label, order in OVERLAP_GROUPS:
        present = [sid for sid in order if sid in by_service]
        if len(present) < 2:
            continue
        keep = by_service[present[0]]
        dropped: list[str] = []
        for sid in present[1:]:
            if sid not in added_service_ids:
                continue  # nunca desativa o que o engenheiro acrescentou à mão
            row = by_service[sid]
            note = f"DESATIVADO AUTOMATICAMENTE: sobrepõe-se a «{keep.get('name')}» ({label})."
            await rest(token, "proposal_items", method="PATCH", params={"id": f"eq.{row['id']}"},
                       body={"enabled": False,
                             "internal_note": f"{note} | {row.get('internal_note') or ''}"[:4000]},
                       prefer="return=minimal")
            dropped.append(str(row.get("name")))
        if dropped:
            messages.append(f"{label}: mantido «{keep.get('name')}»; desativado(s): {', '.join(dropped)}")
    return messages