from __future__ import annotations

import asyncio
from typing import Any

from app.services import field_activities as fa
from app.supabase_rest import rest


def _in(values) -> str | None:
    vals = sorted({str(v).strip() for v in values if str(v or "").strip()})
    if not vals:
        return None
    return "in.(" + ",".join('"' + v.replace('"', "") + '"' for v in vals) + ")"


async def _fetch(token, table, select, column, values, extra=None):
    flt = _in(values)
    if not flt:
        return []
    rows = await rest(token, table, params={"select": select, column: flt, "limit": "5000", **(extra or {})})
    return rows if isinstance(rows, list) else []


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def build_item_details(token: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    service_ids = {str(i["service_id"]).strip() for i in items if i.get("service_id")}
    if not service_ids:
        return {}

    services, act_res, durations, test_links, deps_out, deps_in = await asyncio.gather(
        _fetch(token, "services",
               "service_id,name,unit,category,technical_basis,selling_price,technical_hours,"
               "equipment_cost,laboratory_cost,travel_cost", "service_id", service_ids),
        _fetch(token, "activity_resources",
               "service_id,resource_id,role,quantity,quantity_rule,mandatory,conditional,condition,"
               "duration_minutes,notes", "service_id", service_ids, {"active": "eq.true"}),
        _fetch(token, "activity_duration_rules",
               "service_id,duration_minutes,quantity_rule,minimum_quantity,maximum_quantity,team_size,"
               "condition,priority,notes", "service_id", service_ids,
               {"active": "eq.true", "order": "priority.asc"}),
        _fetch(token, "kb_test_services", "test_code,service_id", "service_id", service_ids),
        _fetch(token, "diagnostic_activity_dependencies",
               "service_id,followup_service_id,relation,quantity_ratio,note", "service_id", service_ids),
        _fetch(token, "diagnostic_activity_dependencies",
               "service_id,followup_service_id,relation,quantity_ratio,note", "followup_service_id", service_ids),
    )

    test_codes = {str(r["test_code"]).strip() for r in test_links if r.get("test_code")}
    proc_tests, kb_tests = await asyncio.gather(
        _fetch(token, "technical_procedure_tests", "procedure_id,test_code,role,notes",
               "test_code", test_codes, {"active": "eq.true"}),
        _fetch(token, "kb_tests", "code,name", "code", test_codes),
    )
    procedure_ids = {str(r["procedure_id"]) for r in proc_tests if r.get("procedure_id")}
    procedures, proc_res = await asyncio.gather(
        _fetch(token, "technical_procedures", "id,code,title", "id", procedure_ids,
               {"active": "eq.true", "status": "eq.ACTIVE"}),
        _fetch(token, "technical_procedure_resources", "procedure_id,resource_id,role,notes",
               "procedure_id", procedure_ids, {"active": "eq.true"}),
    )

    related_ids = ({str(d["followup_service_id"]) for d in deps_out if d.get("followup_service_id")}
                   | {str(d["service_id"]) for d in deps_in if d.get("service_id")})
    resource_ids = ({str(r["resource_id"]) for r in act_res if r.get("resource_id")}
                    | {str(r["resource_id"]) for r in proc_res if r.get("resource_id")})
    resources, related = await asyncio.gather(
        _fetch(token, "resources", "id,resource_id,name,resource_type,unit,requires_calibration,"
               "can_be_rented,external_resource,cost_rate,rental_rate", "id", resource_ids),
        _fetch(token, "services", "service_id,name", "service_id", related_ids - service_ids),
    )

    services_by_id = {str(s["service_id"]).strip(): s for s in services}
    resources_by_id = {str(r["id"]): r for r in resources}
    names = {sid: s.get("name") for sid, s in services_by_id.items()}
    names.update({str(r["service_id"]): r.get("name") for r in related})
    for it in items:
        if it.get("service_id"):
            names[str(it["service_id"])] = it.get("name") or names.get(str(it["service_id"]))

    group = lambda rows, key: _group_by(rows, key)  # noqa: E731
    act_by_service = group(act_res, "service_id")
    dur_by_service = group(durations, "service_id")
    proc_by_id = {str(p["id"]): p for p in procedures}
    proc_res_by_proc = group(proc_res, "procedure_id")
    test_name = {str(t["code"]): t.get("name") for t in kb_tests}
    tests_by_service: dict[str, list[str]] = {}
    for link in test_links:
        tests_by_service.setdefault(str(link["service_id"]), []).append(str(link["test_code"]))
    procs_by_test: dict[str, list[str]] = {}
    for row in proc_tests:
        if str(row.get("procedure_id")) in proc_by_id:
            procs_by_test.setdefault(str(row["test_code"]), []).append(str(row["procedure_id"]))

    out: dict[str, Any] = {}
    for item in items:
        sid = str(item.get("service_id") or "").strip()
        service = services_by_id.get(sid)
        if not service:
            out[item["id"]] = {"linked": False}
            continue
        qty = float(item.get("quantity") or 0)

        rule, needs_check = fa._select_duration_rule(sid, dur_by_service, qty)
        duration = None
        if rule and fa._to_int(rule.get("duration_minutes"), 0):
            duration = {"minutes": fa._to_int(rule["duration_minutes"]), "team_size": fa._to_int(rule.get("team_size"), 0) or None,
                        "rule": rule.get("quantity_rule"), "condition": rule.get("condition"),
                        "condition_to_confirm": needs_check, "source": "regra de duração"}
        else:
            minutes, source = fa._get_fallback_duration(sid, act_by_service)
            if minutes:
                duration = {"minutes": minutes, "team_size": None, "rule": None, "condition": None,
                            "condition_to_confirm": False, "source": source}

        own_tests = list(dict.fromkeys(tests_by_service.get(sid, [])))
        own_proc_ids = list(dict.fromkeys(p for t in own_tests for p in procs_by_test.get(t, [])))
        merged = fa._merge_resources(
            fa._get_activity_resources(sid, act_by_service, resources_by_id),
            fa._get_procedure_resources(own_proc_ids, proc_res_by_proc, resources_by_id))
        resource_list = [{
            "name": r.get("resource_name"), "type": r.get("resource_type") or "OUTRO",
            "role": r.get("role"), "quantity": _num(r.get("quantity")),
            "mandatory": r.get("mandatory"), "condition": r.get("condition") if r.get("conditional") else None,
            "external": bool((r.get("resource") or {}).get("external_resource")),
            "rentable": bool((r.get("resource") or {}).get("can_be_rented")),
            "needs_calibration": bool((r.get("resource") or {}).get("requires_calibration")),
        } for r in merged]

        equipment, lab, travel, hours = (_num(service.get(k)) for k in
                                         ("equipment_cost", "laboratory_cost", "travel_cost", "technical_hours"))
        direct = sum(v or 0 for v in (equipment, lab, travel))
        selling = _num(service.get("selling_price"))
        _, price_status = fa._price_info(service)

        out[item["id"]] = {
            "linked": True, "note": item.get("internal_note"), "category": service.get("category"),
            "technical_basis": fa._PRICE_NOTE.sub("", str(service.get("technical_basis") or "")).strip(),
            "price_status": price_status,
            "cost": {"technical_hours": hours, "equipment": equipment, "laboratory": lab, "travel": travel,
                     "direct_costs_per_unit": direct, "catalog_price": selling,
                     "margin_over_direct": (selling - direct) if selling and selling > 0 else None},
            "duration": duration,
            "labor": [r for r in resource_list if r["type"] == "LABOR"],
            "resources": [r for r in resource_list if r["type"] != "LABOR"],
            "tests": [{"code": c, "name": test_name.get(c)} for c in own_tests],
            "procedures": [{"code": proc_by_id[p].get("code"), "title": proc_by_id[p].get("title")} for p in own_proc_ids],
            "triggers": [{"service_id": d["followup_service_id"], "name": names.get(str(d["followup_service_id"])),
                          "relation": d.get("relation"), "note": d.get("note"),
                          "quantity": round(qty * (_num(d.get("quantity_ratio")) or 1), 2)}
                         for d in deps_out if str(d.get("service_id")) == sid],
            "required_by": [{"service_id": d["service_id"], "name": names.get(str(d["service_id"])),
                             "relation": d.get("relation"), "note": d.get("note")}
                            for d in deps_in if str(d.get("followup_service_id")) == sid],
        }
    return out


def _group_by(rows, key):
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(str(row.get(key) or ""), []).append(row)
    return result