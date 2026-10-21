from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.supabase_rest import rest

BASE = "BASE"
CONDITIONAL = "CONDITIONAL"
STRONG_MATCH = 60
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
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def client_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            f"{key}: {item}" for key, item in value.items() if item is not None
        )
    if isinstance(value, list):
        return " ".join(client_text(item) for item in value)
    return str(value)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _group(value: Any) -> str:
    return str(value or "").strip().upper()


def _pathology_group(value: Any) -> str:
    """Extrai o grupo de códigos como PAT-AL-001 sem confundir nomes de categorias."""
    code = _group(value)
    match = re.match(r"^(?:PAT|PATH|PATOLOGIA)-([A-Z]{2})-(?:\d+|[A-Z0-9-]+)$", code)
    if match:
        return match.group(1)
    # Também aceita grupos curtos diretamente, por exemplo AL, BA, HU ou IH.
    if re.fullmatch(r"[A-Z]{2}", code):
        return code
    return ""


def _price_info(service: dict[str, Any]) -> tuple[float, str]:
    """Distingue preço de catálogo, zero definido e preço desconhecido.

    Devolve (valor, estado): CATALOG (>0), ZERO_IN_CATALOG (0 definido) ou UNKNOWN
    (vazio, inválido ou negativo). UNKNOWN nunca deve ser lido como serviço gratuito.
    """
    raw = (service or {}).get("selling_price")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 0.0, "UNKNOWN"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0, "UNKNOWN"
    if value != value or value < 0:
        return 0.0, "UNKNOWN"
    if value == 0:
        return 0.0, "ZERO_IN_CATALOG"
    return value, "CATALOG"


def _dependency_target(dependency: dict[str, Any]) -> str:
    return str(
        dependency.get("followup_service_id")
        or dependency.get("target_service_id")
        or dependency.get("dependent_service_id")
        or ""
    ).strip()


def _dependency_processing_order(roots: list[str], edges_by_source: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Ordem topológica (pós-ordem inversa): cada atividade só é processada depois
    de todas as que a justificam, por isso cada dependência é tratada uma única vez
    e já com a classe/condições finais da origem. Ciclos não geram repetições."""
    def targets(source: str) -> list[str]:
        return [t for t in (_dependency_target(d) for d in edges_by_source.get(source, [])) if t]

    visited: set[str] = set()
    postorder: list[str] = []
    for root in roots:
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, iter(targets(root)))]
        while stack:
            node, iterator = stack[-1]
            for nxt in iterator:
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append((nxt, iter(targets(nxt))))
                    break
            else:
                postorder.append(node)
                stack.pop()
    postorder.reverse()
    return postorder


def _dependency_edges(dependencies: list[dict[str, Any]]) -> list[tuple[str, str]]:
    edges = []
    for dependency in dependencies:
        source = str(
            dependency.get("service_id")
            or dependency.get("source_service_id")
            or dependency.get("parent_service_id")
            or ""
        ).strip()
        target = str(
            dependency.get("followup_service_id")
            or dependency.get("target_service_id")
            or dependency.get("dependent_service_id")
            or ""
        ).strip()
        if source and target:
            edges.append((source, target))
    return list(dict.fromkeys(edges))


def _find_dependency_cycles(dependencies: list[dict[str, Any]]) -> list[list[str]]:
    """Deteta ciclos no grafo de dependências sem bloquear o planeamento."""
    graph: dict[str, list[str]] = {}
    for source, target in _dependency_edges(dependencies):
        graph.setdefault(source, []).append(target)
    state: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in graph.get(node, []):
            if state.get(target, 0) == 0:
                visit(target)
            elif state.get(target) == 1:
                start = stack.index(target)
                cycle = stack[start:] + [target]
                # Normaliza a representação para não repetir o mesmo ciclo.
                core = cycle[:-1]
                if core:
                    rotations = [tuple(core[i:] + core[:i]) for i in range(len(core))]
                    key = min(rotations)
                    if key not in seen_cycles:
                        seen_cycles.add(key)
                        cycles.append(cycle)
        stack.pop()
        state[node] = 2

    for node in list(graph):
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


class _Plan:
    def __init__(self, catalog: dict[str, dict[str, Any]]) -> None:
        self.catalog = catalog
        self.items: dict[str, dict[str, Any]] = {}
        self.unmapped: list[dict[str, Any]] = []
        self.flags: list[dict[str, Any]] = []

    def add(
        self,
        service_id: str,
        *,
        activity_class: str = BASE,
        reason: str = "",
        condition: str | None = None,
        quantity: float = 1,
        parent_service_id: str | None = None,
        rule_code: str | None = None,
        technical_basis: str | None = None,
        promote: bool = True,
    ) -> None:
        service_id = str(service_id or "").strip()
        if not service_id:
            return
        catalog_item = self.catalog.get(service_id)
        if not catalog_item:
            if not any(x.get("service_id") == service_id for x in self.unmapped):
                self.unmapped.append({"service_id": service_id, "name": service_id, "activity_class": activity_class})
            return
        activity_class = BASE if str(activity_class).upper() == BASE else CONDITIONAL
        item = self.items.get(service_id)
        if item is None:
            item = {
                "service_id": service_id,
                "name": catalog_item.get("name") or service_id,
                "unit": catalog_item.get("unit") or "un",
                "activity_class": activity_class,
                "quantity": max(float(quantity or 1), 1),
                "conditions": [],
                "reasons": [],
                "rule_codes": [],
                "parent_service_id": parent_service_id,
                "technical_basis": technical_basis or catalog_item.get("technical_basis") or "",
            }
            self.items[service_id] = item
        else:
            # Só uma justificação própria (regra) promove CONDITIONAL a BASE; as
            # dependências usam promote=False. As condições nunca são apagadas.
            if activity_class == BASE and promote:
                item["activity_class"] = BASE
            item["quantity"] = max(float(item.get("quantity") or 1), float(quantity or 1))
            if parent_service_id and not item.get("parent_service_id"):
                item["parent_service_id"] = parent_service_id
            if technical_basis and not item.get("technical_basis"):
                item["technical_basis"] = technical_basis
        if reason and reason not in item["reasons"]:
            item["reasons"].append(reason)
        if condition and item["activity_class"] == CONDITIONAL and condition not in item["conditions"]:
            item["conditions"].append(condition)
        if rule_code and rule_code not in item["rule_codes"]:
            item["rule_codes"].append(rule_code)


def _rule_matches(rule: dict[str, Any], *, corpus: str, pathology_groups: set[str], storeys: int, electrical_only: bool) -> bool:
    """Avalia as regras usando o esquema real de diagnostic_activity_rules."""
    trigger_type = _group(
        rule.get("trigger_type")
        or rule.get("condition_type")
        or rule.get("match_type")
        or "ALWAYS"
    )
    value = str(
        rule.get("trigger_value")
        or rule.get("condition_value")
        or rule.get("condition")
        or rule.get("trigger_condition")
        or ""
    ).strip()

    if trigger_type in {"ALWAYS", ""}:
        return True
    if trigger_type in {"PATHOLOGY_GROUP", "PATHOLOGY", "GROUP"}:
        wanted = _group(value)
        return bool(wanted and wanted in pathology_groups)
    if trigger_type in {"MIN_STOREYS", "MIN_FLOORS"}:
        return storeys >= _to_int(value, 0)
    if trigger_type in {"TERM", "TEXT", "CONTAINS"}:
        return bool(fold(value) and fold(value) in corpus)
    if trigger_type in {"ELECTRICAL", "ELECTRICAL_ONLY"}:
        return electrical_only
    # Alguns registos antigos guardavam o termo no campo trigger_condition.
    if trigger_type in {"KEYWORD", "TEXT_MATCH"}:
        term = fold(rule.get("trigger_condition") or value)
        return bool(term and term in corpus)
    return False


def _normalise_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)) or hasattr(value, "__next__"):
        return list(value)
    return [value]

def _build_corpus(fields: dict[str, Any], raw_text: str, technical: dict[str, Any] | None) -> str:
    return fold(" ".join((raw_text, client_text(fields), client_text(technical or {}))))


def _is_electrical_request(corpus: str, fields: dict[str, Any]) -> bool:
    text = f"{corpus} {fold(fields.get('category') or fields.get('service_category'))} {fold(client_text(fields.get('requested_services') or fields.get('services')))}"
    return any(fold(term) in text for term in (
        "eletrica", "eléctrica", "electrica", "instalacao eletrica", "instalacoes eletricas",
        "instalação elétrica", "instalações elétricas", "quadro eletrico", "quadro elétrico",
        "circuito", "cabo", "tomada", "disjuntor",
    ))


def plan_field_activities(*, fields: dict[str, Any], rules: list[dict[str, Any]], catalog: dict[str, dict[str, Any]], services_by_test: dict[str, list[str]], candidates: list[dict[str, Any]] | None, raw_text: str = "") -> dict[str, Any]:
    candidates = candidates or []
    corpus = _build_corpus(fields, raw_text, {"candidates": candidates})
    pathology_groups: set[str] = set()
    for candidate in candidates:
        # Prioriza o grupo explícito; se vier apenas PAT-AL-001, extrai AL.
        explicit_group = candidate.get("pathology_group") or candidate.get("group")
        pathology_code = candidate.get("pathology_code") or candidate.get("code")
        group = _pathology_group(explicit_group) or _pathology_group(pathology_code)
        if group:
            pathology_groups.add(group)
    storeys = max(_to_int(fields.get("storeys") or fields.get("floors") or fields.get("number_of_floors"), 0), 0)
    electrical_only = _is_electrical_request(corpus, fields)
    plan = _Plan(catalog)
    for rule in rules:
        if not _rule_matches(rule, corpus=corpus, pathology_groups=pathology_groups, storeys=storeys, electrical_only=electrical_only):
            continue
        service_id = str(rule.get("service_id") or rule.get("activity_service_id") or "").strip()
        if not service_id:
            continue
        activity_class = _group(rule.get("activity_class")) or BASE
        trigger_condition = str(rule.get("trigger_condition") or "").strip()
        technical_notes = str(rule.get("technical_notes") or "").strip()
        reason = str(rule.get("reason") or technical_notes or trigger_condition).strip()
        condition = trigger_condition or technical_notes or f"Condição definida pela regra {rule.get('code') or service_id}."
        if activity_class != CONDITIONAL:
            condition = None
        quantity = _to_float(
            rule.get("quantity_value")
            if rule.get("quantity_value") is not None
            else rule.get("fixed_quantity", rule.get("quantity", 1)),
            1,
        )
        if quantity <= 0:
            quantity = 1
        plan.add(
            service_id,
            activity_class=activity_class,
            reason=reason or f"Regra {rule.get('code') or rule.get('id') or service_id}",
            condition=condition,
            quantity=quantity,
            rule_code=str(rule.get("code") or rule.get("id") or ""),
            technical_basis=None,
        )
    for candidate in candidates:
        tests = candidate.get("tests") or candidate.get("recommended_tests") or candidate.get("technical_tests") or []
        candidate_score = _to_float(candidate.get("score") or candidate.get("similarity") or candidate.get("confidence") or candidate.get("match_percent"), 0)
        if candidate_score <= 1:
            candidate_score *= 100
        for test in _normalise_list(tests):
            if isinstance(test, dict):
                test_code = str(test.get("code") or test.get("test_code") or "").strip()
                test_score = _to_float(test.get("score") or test.get("similarity") or candidate_score, candidate_score)
                if test_score <= 1:
                    test_score *= 100
            else:
                test_code = str(test or "").strip()
                test_score = candidate_score
            # Os códigos de ensaio são tratados sem distinção entre maiúsculas/minúsculas.
            path_code = str(candidate.get("pathology_code") or candidate.get("code") or "").strip()
            path_name = str(candidate.get("name") or "").strip()
            path_label = " ".join(part for part in (path_code, path_name) if part) or "a patologia suspeita"
            strong = test_score >= STRONG_MATCH
            for service_id in services_by_test.get(test_code.upper(), services_by_test.get(test_code, [])):
                # A correspondência textual é só um indicador: nunca torna a atividade BASE.
                # BASE só vem de regras técnicas (diagnostic_activity_rules) ou de dependências de uma BASE.
                plan.add(
                    service_id,
                    activity_class=CONDITIONAL,
                    reason=f"Ensaio {test_code} sugerido pela base técnica para {path_label}"
                           + (" (correspondência textual forte; indicador, não decisivo)" if strong else ""),
                    condition=f"Executar se a inspeção de campo confirmar indícios compatíveis com {path_label} (ensaio {test_code}).",
                )
    if electrical_only:
        for service_id, keywords in ELECTRICAL_SERVICE_KEYWORDS:
            if any(fold(keyword) in corpus for keyword in keywords) and service_id in catalog:
                plan.add(service_id, activity_class=BASE, reason="Pedido com necessidade elétrica explícita.")
    if any(_group(catalog.get(item["service_id"], {}).get("category")) in FIELD_TEST_CATEGORIES for item in plan.items.values()) and REPORT_SERVICE_ID in catalog:
        plan.add(REPORT_SERVICE_ID, activity_class=BASE, reason="Relatório associado à execução de ensaios/monitorização.")
    dependencies = fields.get("_dependencies") or []
    # Percorre as dependências como grafo: cada aresta é processada uma vez,
    # permitindo cadeias transitivas sem limite arbitrário nem ciclos infinitos.
    edges_by_source: dict[str, list[dict[str, Any]]] = {}
    for dependency in dependencies:
        source = str(
            dependency.get("service_id")
            or dependency.get("source_service_id")
            or dependency.get("parent_service_id")
            or ""
        ).strip()
        target = str(
            dependency.get("followup_service_id")
            or dependency.get("target_service_id")
            or dependency.get("dependent_service_id")
            or ""
        ).strip()
        if source and target:
            edges_by_source.setdefault(source, []).append(dependency)

    order = _dependency_processing_order(list(plan.items.keys()), edges_by_source)
    for source in order:
        source_item = plan.items.get(source)
        if not source_item:
            continue
        for dependency in edges_by_source.get(source, []):
            target = _dependency_target(dependency)
            if not target:
                continue
            ratio = _to_float(dependency.get("quantity_ratio"), 1)
            target_quantity = max(_to_float(source_item.get("quantity"), 1) * (ratio if ratio > 0 else 1), 1)
            relation = _group(dependency.get("relation"))
            explicit_note = str(dependency.get("note") or dependency.get("notes") or "").strip()
            note = explicit_note or "Dependência técnica."

            source_class = source_item.get("activity_class", CONDITIONAL)
            requested_class = _group(dependency.get("activity_class"))
            if source_class == CONDITIONAL:
                dependency_class = CONDITIONAL  # nunca fica mais obrigatória do que a origem
            elif requested_class in {BASE, CONDITIONAL}:
                dependency_class = requested_class
            else:
                dependency_class = source_class

            condition = None
            if dependency_class == CONDITIONAL:
                parts = list(source_item.get("conditions") or []) + ([explicit_note] if explicit_note else [])
                if not parts:
                    parts = [f"Só se a atividade «{source_item.get('name') or source}» for executada."]
                condition = "; ".join(_unique_strings(parts))
            plan.add(
                target,
                activity_class=dependency_class,
                reason=f"Dependência {relation or 'técnica'} de {source}: {note}",
                condition=condition,
                quantity=target_quantity,
                parent_service_id=source,
                technical_basis=source_item.get("technical_basis") or None,
                promote=False,
            )

    for cycle in _find_dependency_cycles(dependencies):
        if any(service_id in plan.items for service_id in cycle):
            plan.flags.append({
                "severity": "WARNING",
                "code": "DEPENDENCY_CYCLE",
                "message": "Foi detetado um ciclo nas dependências técnicas: " + " -> ".join(cycle),
            })
    hypotheses: list[dict[str, Any]] = []
    for candidate in candidates:
        # A solução vem aninhada na patologia candidata: é essa a relação segura.
        candidate_code = str(candidate.get("pathology_code") or candidate.get("code") or "").strip()
        candidate_evidence = candidate.get("evidence")
        for solution in _normalise_list(candidate.get("solutions") or candidate.get("solution_hypotheses") or candidate.get("recommended_solutions")):
            if isinstance(solution, dict):
                item = dict(solution)
            elif solution:
                item = {"solution": str(solution)}
            else:
                continue
            if candidate_code and not (item.get("pathology_code") or item.get("pathology") or item.get("pathology_id")):
                item["pathology_code"] = candidate_code
            if candidate_evidence:
                item["_candidate_evidence"] = candidate_evidence
            hypotheses.append(item)
    if plan.unmapped:
        for unmapped in plan.unmapped:
            plan.flags.append({
                "severity": "CRITICAL",
                "code": "UNMAPPED_SERVICE",
                "message": f"A atividade {unmapped.get('service_id')} não existe no catálogo ativo de serviços.",
            })
    activities = list(plan.items.values())
    activities.sort(key=lambda item: (0 if item["activity_class"] == BASE else 1, item["name"]))
    return {"activities": activities, "unmapped": plan.unmapped, "flags": plan.flags, "hypotheses": hypotheses, "pathology_groups": sorted(pathology_groups)}


def _validate_plan(activities: list[dict[str, Any]], catalog: dict[str, dict[str, Any]], *, raw_text: str = "") -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    if not activities:
        flags.append({"severity": "CRITICAL", "code": "NO_ACTIVITY", "message": "Não foi possível determinar atividades de diagnóstico a partir dos dados disponíveis."})
    for activity in activities:
        service_id = activity.get("service_id")
        if service_id not in catalog:
            flags.append({"severity": "CRITICAL", "code": "UNMAPPED", "message": f"Serviço {service_id} não existe no catálogo."})
        if activity.get("activity_class") == CONDITIONAL and not activity.get("conditions"):
            flags.append({"severity": "WARNING", "code": "CONDITIONAL_WITHOUT_TRIGGER", "message": f"A atividade {activity.get('name')} é condicional mas não tem condição de disparo."})
        if activity.get("activity_class") == CONDITIONAL and not fold(activity.get("technical_basis")):
            flags.append({"severity": "WARNING", "code": "CONDITIONAL_WITHOUT_BASIS", "message": f"A atividade condicional {activity.get('name')} não tem fundamentação técnica."})
    if raw_text and "segur" in fold(raw_text):
        flags.append({"severity": "INFO", "code": "SAFETY", "message": "Rever condições de segurança e acesso antes da execução em campo."})
    return flags


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    for value in _normalise_list(values):
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _resource_label(resource: dict[str, Any]) -> str:
    return str(resource.get("name") or resource.get("resource_id") or resource.get("id") or "").strip()


def _resource_code(resource: dict[str, Any]) -> str:
    return str(resource.get("resource_id") or resource.get("id") or "").strip()


def _resource_type(resource: dict[str, Any]) -> str:
    return str(resource.get("resource_type") or "").strip().upper()


def _select_duration_rule(service_id: str, duration_rules_by_service: dict[str, list[dict[str, Any]]], quantity: float) -> tuple[dict[str, Any] | None, bool]:
    """Escolhe UMA regra aplicável à quantidade. Não usa regras fora da gama.
    Prefere regras sem condição em texto; devolve (regra, condição_por_confirmar)."""
    applicable = []
    for row in duration_rules_by_service.get(service_id, []):
        if row.get("minimum_quantity") is not None and quantity < _to_float(row.get("minimum_quantity")):
            continue
        if row.get("maximum_quantity") is not None and quantity > _to_float(row.get("maximum_quantity")):
            continue
        applicable.append(row)
    if not applicable:
        return None, False
    unconditional = [row for row in applicable if not str(row.get("condition") or "").strip()]
    pool = unconditional or applicable
    chosen = sorted(pool, key=lambda row: (_to_int(row.get("priority"), 999999), -_to_int(row.get("duration_minutes"), 0)))[0]
    return chosen, not unconditional


def _get_fallback_duration(service_id: str, activity_resources_by_service: dict[str, list[dict[str, Any]]]) -> tuple[int | None, str]:
    durations = [_to_int(row.get("duration_minutes"), 0) for row in activity_resources_by_service.get(service_id, []) if _to_int(row.get("duration_minutes"), 0) > 0]
    return (max(durations), "activity_resources.max_duration_minutes") if durations else (None, "")


def _get_activity_resources(service_id: str, activity_resources_by_service: dict[str, list[dict[str, Any]]], resources_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in activity_resources_by_service.get(service_id, []):
        resource_id = str(row.get("resource_id") or "").strip()
        resource = resources_by_id.get(resource_id, {})
        result.append({**row, "resource": resource, "resource_name": _resource_label(resource) or resource_id, "resource_code": _resource_code(resource) or resource_id, "resource_type": _resource_type(resource)})
    return result


def _get_procedure_resources(procedure_ids: list[str], procedure_resources_by_procedure: dict[str, list[dict[str, Any]]], resources_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for procedure_id in procedure_ids:
        for row in procedure_resources_by_procedure.get(procedure_id, []):
            resource_id = str(row.get("resource_id") or "").strip()
            resource = resources_by_id.get(resource_id, {})
            result.append({**row, "procedure_id": procedure_id, "resource": resource, "resource_name": _resource_label(resource) or resource_id, "resource_code": _resource_code(resource) or resource_id, "resource_type": _resource_type(resource)})
    return result


def _build_labor_summary(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in resources:
        resource = item.get("resource") or {}
        if _resource_type(resource) != "LABOR":
            continue
        code = item.get("resource_code") or item.get("resource_id")
        if code in seen:
            continue
        seen.add(code)
        result.append({"resource_id": code, "name": item.get("resource_name") or code, "quantity": _to_float(item.get("quantity"), 1), "role": item.get("role")})
    return result


def _merge_resources(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for group in groups:
        for item in group:
            key = (str(item.get("resource_code") or item.get("resource_id") or ""), str(item.get("role") or ""))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def _enrich_plan_activities(activities: list[dict[str, Any]], *, catalog: dict[str, dict[str, Any]], procedures_by_service: dict[str, list[str]], procedures_by_id: dict[str, dict[str, Any]], procedure_resources_by_procedure: dict[str, list[dict[str, Any]]], activity_resources_by_service: dict[str, list[dict[str, Any]]], resources_by_id: dict[str, dict[str, Any]], duration_rules_by_service: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    enriched = []
    for activity in activities:
        service_id = activity["service_id"]
        catalog_item = catalog.get(service_id, {})
        rule_row, rule_needs_check = _select_duration_rule(service_id, duration_rules_by_service, _to_float(activity.get("quantity"), 1))
        duration = (_to_int(rule_row.get("duration_minutes"), 0) or None) if rule_row else None
        duration_source = ("activity_duration_rules" + (" (condição por confirmar)" if rule_needs_check else "")) if duration else ""
        team_size = _to_int(rule_row.get("team_size"), 0) if (rule_row and duration) else 0
        if duration is None:
            duration, duration_source = _get_fallback_duration(service_id, activity_resources_by_service)
        activity_resources = _get_activity_resources(service_id, activity_resources_by_service, resources_by_id)
        procedure_ids = procedures_by_service.get(service_id, [])
        procedure_rows = [procedures_by_id[pid] for pid in procedure_ids if pid in procedures_by_id]
        procedure_resources = _get_procedure_resources(procedure_ids, procedure_resources_by_procedure, resources_by_id)
        resources = _merge_resources(activity_resources, procedure_resources)
        enriched.append({**activity, "technical_basis": activity.get("technical_basis") or catalog_item.get("technical_basis") or "", "trigger_condition": "; ".join(activity.get("conditions") or []) if activity.get("activity_class") == CONDITIONAL else None, "duration_minutes": duration, "duration_source": duration_source, "team_size": team_size, "resources": resources, "resource_names": _unique_strings(item.get("resource_name") for item in resources), "labor": _build_labor_summary(resources), "procedure_codes": _unique_strings(row.get("code") for row in procedure_rows), "procedure_names": _unique_strings(row.get("title") for row in procedure_rows), "procedures": procedure_rows})
    return enriched


async def load_reference_data(token: str) -> dict[str, Any]:
    rules = await rest(token, "diagnostic_activity_rules", params={"active": "eq.true", "select": "*", "order": "priority.asc", "limit": "1000"})
    rules = rules if isinstance(rules, list) else []
    # A tabela de dependências não tem colunas active nem priority.
    dependencies = await rest(token, "diagnostic_activity_dependencies", params={"select": "service_id,followup_service_id,relation,quantity_ratio,note", "limit": "5000"})
    dependencies = dependencies if isinstance(dependencies, list) else []
    services = await rest(token, "services", params={"active": "eq.true", "select": "service_id,name,unit,technical_basis,category,selling_price,technical_hours,equipment_cost,laboratory_cost,travel_cost", "order": "service_id.asc", "limit": "5000"})
    services = services if isinstance(services, list) else []
    catalog = {str(s.get("service_id") or "").strip(): s for s in services if str(s.get("service_id") or "").strip()}
    # As associações reais entre ensaios e serviços estão em kb_test_services.
    # Não dependemos de test_code em diagnostic_activity_rules, pois essa coluna não existe.
    services_by_test: dict[str, list[str]] = {}
    rows = await rest(
        token,
        "kb_test_services",
        params={"select": "test_code,service_id", "limit": "10000"},
    )
    rows = rows if isinstance(rows, list) else []
    for row in rows:
        test_code = str(row.get("test_code") or "").strip().upper()
        service_id = str(row.get("service_id") or "").strip()
        if test_code and service_id in catalog:
            services_by_test.setdefault(test_code, []).append(service_id)
    for test_code in list(services_by_test):
        services_by_test[test_code] = list(dict.fromkeys(services_by_test[test_code]))
    procedures = await rest(token, "technical_procedures", params={"active": "eq.true", "status": "eq.ACTIVE", "select": "*", "order": "code.asc", "limit": "5000"})
    procedures = procedures if isinstance(procedures, list) else []
    procedures_by_id = {str(p.get("id") or "").strip(): p for p in procedures if str(p.get("id") or "").strip()}
    procedure_test_rows = await rest(token, "technical_procedure_tests", params={"active": "eq.true", "select": "id,procedure_id,test_code,role,notes", "limit": "5000"})
    procedure_test_rows = procedure_test_rows if isinstance(procedure_test_rows, list) else []
    procedures_by_service: dict[str, list[str]] = {}
    for row in procedure_test_rows:
        pid = str(row.get("procedure_id") or "").strip()
        tc = str(row.get("test_code") or "").strip()
        if not pid or not tc or pid not in procedures_by_id:
            continue
        for sid in services_by_test.get(tc, []):
            procedures_by_service.setdefault(sid, []).append(pid)
    for sid in list(procedures_by_service):
        procedures_by_service[sid] = list(dict.fromkeys(procedures_by_service[sid]))
    procedure_resource_rows = await rest(token, "technical_procedure_resources", params={"active": "eq.true", "select": "id,procedure_id,resource_id,role,notes", "limit": "5000"})
    procedure_resource_rows = procedure_resource_rows if isinstance(procedure_resource_rows, list) else []
    procedure_resources_by_procedure: dict[str, list[dict[str, Any]]] = {}
    resource_ids: set[str] = set()
    for row in procedure_resource_rows:
        pid = str(row.get("procedure_id") or "").strip()
        rid = str(row.get("resource_id") or "").strip()
        if pid and rid:
            procedure_resources_by_procedure.setdefault(pid, []).append(row)
            resource_ids.add(rid)
    activity_resource_rows = await rest(token, "activity_resources", params={"active": "eq.true", "select": "id,service_id,resource_id,role,quantity,quantity_rule,mandatory,conditional,condition,preferred_source,pricing_mode,duration_minutes,notes", "limit": "10000"})
    activity_resource_rows = activity_resource_rows if isinstance(activity_resource_rows, list) else []
    activity_resources_by_service: dict[str, list[dict[str, Any]]] = {}
    for row in activity_resource_rows:
        sid = str(row.get("service_id") or "").strip()
        rid = str(row.get("resource_id") or "").strip()
        if sid and rid:
            activity_resources_by_service.setdefault(sid, []).append(row)
            resource_ids.add(rid)
    resources_by_id: dict[str, dict[str, Any]] = {}
    if resource_ids:
        joined = ",".join(sorted(resource_ids))
        resources = await rest(token, "resources", params={"id": f"in.({joined})", "select": "id,resource_id,name,resource_type,description,unit,reusable,stock_controlled,requires_calibration,requires_maintenance,can_be_rented,external_resource,availability_mode,cost_rate,rental_rate,active", "limit": "5000"})
        resources = resources if isinstance(resources, list) else []
        resources_by_id = {str(r.get("id") or "").strip(): r for r in resources if str(r.get("id") or "").strip()}
    duration_rows = await rest(token, "activity_duration_rules", params={"active": "eq.true", "select": "id,service_id,duration_minutes,quantity_rule,minimum_quantity,maximum_quantity,team_size,condition,priority,notes", "order": "priority.asc", "limit": "5000"})
    duration_rows = duration_rows if isinstance(duration_rows, list) else []
    duration_rules_by_service: dict[str, list[dict[str, Any]]] = {}
    for row in duration_rows:
        sid = str(row.get("service_id") or "").strip()
        if sid:
            duration_rules_by_service.setdefault(sid, []).append(row)
    return {"rules": rules, "dependencies": dependencies, "catalog": catalog, "services_by_test": services_by_test, "procedures_by_id": procedures_by_id, "procedures_by_service": procedures_by_service, "procedure_tests": procedure_test_rows, "procedure_resources_by_procedure": procedure_resources_by_procedure, "resources_by_id": resources_by_id, "activity_resources_by_service": activity_resources_by_service, "duration_rules_by_service": duration_rules_by_service}


def _build_internal_note(activity: dict[str, Any]) -> str:
    parts = []
    reasons = _unique_strings(activity.get("reasons"))
    if reasons:
        parts.append("Motivo: " + "; ".join(reasons))
    procedures = _unique_strings(activity.get("procedure_codes") or activity.get("procedures"))
    if procedures:
        parts.append("Procedimentos: " + ", ".join(procedures))
    resources = _unique_strings(activity.get("resource_names"))
    if resources:
        parts.append("Recursos: " + ", ".join(resources))
    if activity.get("duration_minutes"):
        parts.append(f"Duração prevista: {activity['duration_minutes']} min.")
    team_size = _to_int(activity.get("team_size"), 0)
    if team_size:
        parts.append(f"Equipa prevista: {team_size}.")
    if activity.get("activity_class") == CONDITIONAL and activity.get("trigger_condition"):
        parts.append(f"Disparo condicional: {activity['trigger_condition']}")
    return " | ".join(parts)[:4000]


def _build_technical_basis(activity: dict[str, Any]) -> str:
    basis = _PRICE_NOTE.sub("", str(activity.get("technical_basis") or "")).strip()
    condition = str(activity.get("trigger_condition") or "").strip()
    if activity.get("activity_class") == CONDITIONAL and condition and condition not in basis:
        basis = f"{basis} Condição de execução: {condition}" if basis else f"Condição de execução: {condition}"
    return basis[:4000]


def _item_rows(proposal_id: str, activities: list[dict[str, Any]], catalog: dict[str, dict[str, Any]], existing_service_ids: set[str] | None = None, start_position: int = 1) -> list[dict[str, Any]]:
    existing_service_ids = existing_service_ids or set()
    rows = []
    position = start_position
    local_service_ids: set[str] = set()
    for activity in activities:
        service_id = str(activity.get("service_id") or "").strip()
        if not service_id or service_id in existing_service_ids or service_id in local_service_ids:
            continue
        service = catalog.get(service_id)
        if not service:
            continue
        selling_price, price_status = _price_info(service)
        internal_note = _build_internal_note(activity)
        if price_status != "CATALOG":
            warning = "PREÇO POR VALIDAR: sem preço no catálogo." if price_status == "UNKNOWN" else "PREÇO POR VALIDAR: o catálogo indica 0, que não significa gratuito."
            internal_note = f"{warning} | {internal_note}" if internal_note else warning
        activity_class = BASE if activity.get("activity_class") == BASE else CONDITIONAL
        rows.append({
            "proposal_id": proposal_id,
            "name": str(service.get("name") or activity.get("name") or service_id).strip(),
            "unit": str(service.get("unit") or activity.get("unit") or "un").strip(),
            "is_optional": False,
            "enabled": True,
            "quantity": max(_to_float(activity.get("quantity"), 1), 1),
            "unit_price": selling_price,
            "origin": "SUGGESTED" if price_status == "CATALOG" else "REQUIRES_REVIEW",
            "service_id": service_id,
            "technical_basis": _build_technical_basis(activity),
            "position": position,
            "activity_class": activity_class,
            "trigger_condition": activity.get("trigger_condition") if activity_class == CONDITIONAL else None,
            "quantity_rule": None,
            "included_in_approved_scope": True,
            "internal_note": internal_note[:4000],
        })
        local_service_ids.add(service_id)
        position += 1
    return rows


async def run_field_activity_engine(token: str, owner_id: str, proposal_id: str, request_id: str, fields: dict[str, Any], raw_text: str = "", technical: dict[str, Any] | None = None) -> dict[str, Any]:
    candidates = []
    if technical:
        candidates = technical.get("pathologies") or technical.get("candidates") or technical.get("diagnostic_candidates") or []
        candidates = candidates if isinstance(candidates, list) else []
    reference = await load_reference_data(token)
    planner_fields = dict(fields or {})
    planner_fields["_dependencies"] = reference["dependencies"]
    planned = plan_field_activities(fields=planner_fields, rules=reference["rules"], catalog=reference["catalog"], services_by_test=reference["services_by_test"], candidates=candidates, raw_text=raw_text)
    activities = _enrich_plan_activities(planned["activities"], catalog=reference["catalog"], procedures_by_service=reference["procedures_by_service"], procedures_by_id=reference["procedures_by_id"], procedure_resources_by_procedure=reference["procedure_resources_by_procedure"], activity_resources_by_service=reference["activity_resources_by_service"], resources_by_id=reference["resources_by_id"], duration_rules_by_service=reference["duration_rules_by_service"])
    flags = list(planned.get("flags") or [])
    flags.extend(_validate_plan(activities, reference["catalog"], raw_text=raw_text))
    existing_rows = await rest(token, "proposal_items", params={"proposal_id": f"eq.{proposal_id}", "select": "id,service_id,position", "order": "position.asc", "limit": "5000"})
    existing_rows = existing_rows if isinstance(existing_rows, list) else []
    existing_service_ids = {str(row.get("service_id") or "").strip() for row in existing_rows if str(row.get("service_id") or "").strip()}
    max_position = max([_to_int(row.get("position"), 0) for row in existing_rows] or [0])
    item_rows = _item_rows(proposal_id=proposal_id, activities=activities, catalog=reference["catalog"], existing_service_ids=existing_service_ids, start_position=max_position + 1)
    created_rows = []
    if item_rows:
        inserted = await rest(token, "proposal_items", method="POST", body=item_rows, prefer="return=representation")
        created_rows = inserted if isinstance(inserted, list) else []
    all_item_rows = existing_rows + created_rows
    item_id_by_service = {str(row.get("service_id") or "").strip(): row.get("id") for row in all_item_rows if row.get("id") and row.get("service_id")}
    for activity in activities:
        parent_service_id = activity.get("parent_service_id")
        service_id = activity.get("service_id")
        if not parent_service_id or not service_id:
            continue
        child_id = item_id_by_service.get(service_id)
        parent_id = item_id_by_service.get(parent_service_id)
        if child_id and parent_id:
            await rest(token, f"proposal_items?id=eq.{child_id}", method="PATCH", body={"parent_item_id": parent_id})
    hypotheses_count = 0
    hypothesis_errors: list[str] = []
    hypotheses = planned.get("hypotheses") or []

    # A tabela proposal_solution_hypotheses não tem a coluna "hypothesis".
    # Usa apenas colunas existentes: pathology_code, solution_code,
    # solution_name, evidence, status e field_note.
    existing_hypotheses: list[dict[str, Any]] = []
    try:
        rows = await rest(
            token,
            "proposal_solution_hypotheses",
            params={
                "request_id": f"eq.{request_id}",
                "select": "pathology_code,solution_code,solution_name,evidence,status,field_note",
                "limit": "5000",
            },
        )
        existing_hypotheses = rows if isinstance(rows, list) else []
    except Exception as exc:
        hypothesis_errors.append(
            f"Não foi possível consultar hipóteses existentes: {exc}"
        )

    existing_keys = {
        (
            str(row.get("pathology_code") or "").strip(),
            str(row.get("solution_code") or "").strip(),
        )
        for row in existing_hypotheses
    }
    seen_keys: set[tuple[str, str]] = set()

    import json

    for original in hypotheses:
        if isinstance(original, dict):
            hypothesis = dict(original)
        elif original is not None and str(original).strip():
            hypothesis = {"solution": str(original).strip()}
        else:
            continue

        pathology_code = str(
            hypothesis.get("pathology_code")
            or hypothesis.get("pathology")
            or hypothesis.get("pathology_id")
            or ""
        ).strip()
        solution_code = str(
            hypothesis.get("solution_code")
            or hypothesis.get("code")
            or hypothesis.get("solution_id")
            or ""
        ).strip()

        solution_value = (
            hypothesis.get("solution_name")
            or hypothesis.get("solution")
            or hypothesis.get("name")
            or hypothesis.get("title")
            or hypothesis.get("recommended_solution")
        )
        if isinstance(solution_value, dict):
            solution_name = str(
                solution_value.get("name")
                or solution_value.get("title")
                or solution_value.get("description")
                or solution_value.get("solution_name")
                or ""
            ).strip()
        else:
            solution_name = str(solution_value or "").strip()

        missing_fields = []
        if not pathology_code:
            missing_fields.append("pathology_code")
        if not solution_code:
            missing_fields.append("solution_code")
        if not solution_name:
            missing_fields.append("solution_name")
        if missing_fields:
            hypothesis_errors.append(
                "Hipótese ignorada porque faltam campos obrigatórios: "
                + ", ".join(missing_fields)
                + f". Dados recebidos: {hypothesis}"
            )
            continue

        key = (pathology_code, solution_code)
        if key in existing_keys or key in seen_keys:
            continue

        evidence_value = (
            hypothesis.get("evidence")
            or hypothesis.get("justification")
            or hypothesis.get("reason")
            or hypothesis.get("technical_basis")
            or hypothesis.get("description")
            or hypothesis.get("rationale")
            or hypothesis.get("_candidate_evidence")
        )
        if isinstance(evidence_value, list) and all(isinstance(x, str) for x in evidence_value):
            evidence = " | ".join(x.strip() for x in evidence_value if x.strip())
        elif isinstance(evidence_value, (dict, list)):
            evidence = json.dumps(
                evidence_value,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        else:
            evidence = str(evidence_value or "").strip()
        if not evidence:
            evidence = json.dumps(
                hypothesis,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )

        field_note_value = hypothesis.get("field_note")
        field_note = (
            str(field_note_value).strip()
            if field_note_value is not None
            else None
        )

        try:
            await rest(
                token,
                "proposal_solution_hypotheses",
                method="POST",
                params={"on_conflict": "request_id,pathology_code,solution_code"},
                body={
                    "request_id": request_id,
                    "pathology_code": pathology_code,
                    "solution_code": solution_code,
                    "solution_name": solution_name,
                    "evidence": evidence,
                    "status": "PREDICTED",
                    "field_note": field_note,
                },
                prefer="resolution=merge-duplicates,return=minimal",
            )
            hypotheses_count += 1
            seen_keys.add(key)
            existing_keys.add(key)
        except Exception as exc:
            hypothesis_errors.append(
                f"Falha ao guardar hipótese {solution_code or pathology_code}: {exc}"
            )
    base = [item for item in activities if item.get("activity_class") == BASE]
    conditional = [item for item in activities if item.get("activity_class") == CONDITIONAL]
    price_review = []
    for item in item_rows:
        _, status = _price_info(reference["catalog"].get(str(item.get("service_id") or ""), {}))
        if status != "CATALOG":
            price_review.append({"service_id": item.get("service_id"), "name": item.get("name"), "price_status": status})
    if price_review:
        flags.append({
            "severity": "WARNING",
            "code": "PRICE_PENDING",
            "message": f"{len(price_review)} serviço(s) sem preço validado. O valor 0 não significa gratuito: o total é provisório até confirmar estes preços.",
            "details": [f"{p['service_id']} ({'sem preço' if p['price_status'] == 'UNKNOWN' else 'catálogo com 0'})" for p in price_review],
        })
    if hypothesis_errors:
        flags.append({
            "severity": "WARNING",
            "code": "HYPOTHESIS_PERSISTENCE",
            "message": "Algumas hipóteses de solução não puderam ser confirmadas como guardadas.",
            "details": hypothesis_errors,
        })
    return {"proposal_id": proposal_id, "request_id": request_id, "added": [str(row.get("service_id")) for row in created_rows if row.get("service_id")], "activities": activities, "base": base, "conditional": conditional, "unmapped": planned.get("unmapped") or [], "flags": flags, "hypotheses": hypotheses_count, "hypothesis_errors": hypothesis_errors, "price_review": price_review, "price_pending": len(price_review), "diagnostic_scope": {"base_count": len(base), "conditional_count": len(conditional), "included_in_approved_scope": True, "client_approval_required_after_diagnostic_approval": False}, "exclusions": list(DEFAULT_EXCLUSIONS)}