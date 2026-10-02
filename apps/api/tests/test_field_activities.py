"""Testes das regras do Motor de Atividades de Campo (sem base de dados)."""
from app.services.field_activities import (
    BASE,
    CONDITIONAL,
    _item_rows,
    plan_field_activities,
)


def svc(service_id, category, name, unit="un", price=0.0, basis=None):
    return {"service_id": service_id, "category": category, "name": name, "unit": unit,
            "selling_price": price, "technical_basis": basis}


CATALOG = {s["service_id"]: s for s in [
    svc("MOB", "SURVEY", "Verba fixa de mobilização", price=900),
    svc("EST_VISUAL", "BUILDING_PATHOLOGY", "Estudo preliminar com inspeção visual", price=2900),
    svc("MAP_FISS", "SURVEY", "Mapeamento de fissuras", "zona"),
    svc("REM_REVEST", "INTRUSIVE", "Remoção localizada de revestimento", "zona",
        basis="Remoção pontual do revestimento. Preço a definir pelo engenheiro."),
    svc("ABERT_LOCAL", "INTRUSIVE", "Abertura localizada", "ponto"),
    svc("EXPOS_ARM", "INTRUSIVE", "Exposição localizada de armadura", "ponto"),
    svc("INSP_INT", "SURVEY", "Inspeção interna", "ponto"),
    svc("FECHO_ABERT", "REINSTATEMENT", "Fecho de abertura", "ponto"),
    svc("REP_REVEST", "REINSTATEMENT", "Reposição de revestimento", "zona"),
    svc("ACESSO_ESP", "LOGISTICS", "Meios de acesso especiais"),
    svc("PACO", "NDT", "Pacometria", "zona", 150),
    svc("CARB", "NDT", "Carbonatação", "ponto", 40),
    svc("REL_ENS", "NDT", "Relatório de ensaios", price=1400),
    svc("PROJ_REAB", "STUDY", "Especificação da solução de reparação"),
    svc("ELEC_INSPECT", "ELECTRICAL_DIAGNOSTIC", "Inspeção elétrica"),
]}


def rule(code, service_id, cls, kind, value=None, cond=None, priority=100):
    return {"code": code, "service_id": service_id, "activity_class": cls, "trigger_type": kind,
            "trigger_value": value, "trigger_condition": cond, "quantity_value": 1, "quantity_rule": "FIXED",
            "priority": priority, "active": True}


RULES = [
    rule("R-MOB", "MOB", BASE, "ALWAYS", priority=10),
    rule("R-VIS", "EST_VISUAL", BASE, "ALWAYS", priority=20),
    rule("R-AL-FISS", "MAP_FISS", BASE, "PATHOLOGY_GROUP", "AL", priority=30),
    rule("R-AL-REV", "REM_REVEST", CONDITIONAL, "PATHOLOGY_GROUP", "AL", "o revestimento impedir a observação", 40),
    rule("R-AL-ABERT", "ABERT_LOCAL", CONDITIONAL, "PATHOLOGY_GROUP", "AL", "for necessário ver o interior", 41),
    rule("R-BA-ARM", "EXPOS_ARM", CONDITIONAL, "PATHOLOGY_GROUP", "BA", "for necessário confirmar as armaduras", 41),
    rule("R-PISOS", "ACESSO_ESP", CONDITIONAL, "MIN_STOREYS", "4", "o acesso exigir plataforma", 60),
    rule("R-FACHADA", "ACESSO_ESP", CONDITIONAL, "TERM", "fachada", "o acesso exigir plataforma", 61),
]
DEPS = [
    {"service_id": "ABERT_LOCAL", "followup_service_id": "INSP_INT", "relation": "FOLLOW_UP", "quantity_ratio": 1},
    {"service_id": "ABERT_LOCAL", "followup_service_id": "FECHO_ABERT", "relation": "REINSTATEMENT", "quantity_ratio": 1},
    {"service_id": "FECHO_ABERT", "followup_service_id": "REP_REVEST", "relation": "REINSTATEMENT", "quantity_ratio": 1},
    {"service_id": "REM_REVEST", "followup_service_id": "REP_REVEST", "relation": "REINSTATEMENT", "quantity_ratio": 1},
    {"service_id": "EXPOS_ARM", "followup_service_id": "REP_REVEST", "relation": "REINSTATEMENT", "quantity_ratio": 1},
]


def cand(code, name, match, tests=(), solutions=()):
    return {"code": code, "name": name, "match_percent": match, "evidence": ["parede com fissuras"],
            "tests": [{"code": c, "name": n} for c, n in tests],
            "solutions": [{"code": c, "name": n} for c, n in solutions]}


def run(fields=None, raw="", candidates=(), tests_map=None, rules=RULES, catalog=CATALOG):
    return plan_field_activities(fields=fields or {}, raw_text=raw, candidates=list(candidates), rules=rules,
                                 dependencies=DEPS, catalog=catalog, services_by_test=tests_map or {})


def by_service(plan):
    return {a["service_id"]: a for a in plan["activities"]}


def test_fissuras_em_parede_prevê_base_condicionais_e_consequências():
    plan = run({"objective": "fissuras numa parede"}, candidates=[cand("PAT-AL-001", "Fissuras verticais", 56,
               solutions=[("SOL-20", "Reparação de alvenaria")])])
    activities = by_service(plan)
    assert {s for s, a in activities.items() if a["activity_class"] == BASE} == {"MOB", "EST_VISUAL", "MAP_FISS"}
    assert {s for s, a in activities.items() if a["activity_class"] == CONDITIONAL} == {
        "REM_REVEST", "ABERT_LOCAL", "INSP_INT", "FECHO_ABERT", "REP_REVEST"}


def test_abertura_traz_inspecao_fecho_e_reposicao_encadeados():
    activities = by_service(run(candidates=[cand("PAT-AL-001", "Fissuras", 50)]))
    assert activities["FECHO_ABERT"]["parent"] == "ABERT_LOCAL"
    assert activities["REP_REVEST"]["activity_class"] == CONDITIONAL
    assert not any(f["code"] == "INTRUSIVE_WITHOUT_REINSTATEMENT" for f in run(
        candidates=[cand("PAT-AL-001", "Fissuras", 50)])["flags"])


def test_exposicao_de_armadura_exige_reposicao():
    activities = by_service(run(candidates=[cand("PAT-BA-030", "Armaduras expostas", 84)]))
    assert "EXPOS_ARM" in activities and "REP_REVEST" in activities


def test_solucao_nunca_vira_atividade_e_fica_como_hipotese():
    plan = run(candidates=[cand("PAT-AL-001", "Fissuras", 56, solutions=[("SOL-20", "Reparação de alvenaria")])])
    assert "PROJ_REAB" not in by_service(plan)
    assert plan["hypotheses"] == [{"pathology_code": "PAT-AL-001", "solution_code": "SOL-20",
                                   "solution_name": "Reparação de alvenaria", "evidence": "parede com fissuras"}]
    assert any("reparação" in e.lower() for e in plan["exclusions"])


def test_ensaio_forte_e_base_e_fraco_e_condicional_com_relatorio():
    plan = run(candidates=[cand("PAT-BA-030", "Armaduras expostas", 84, tests=[("ENS-12", "Pacometria")]),
                           cand("PAT-BA-021", "Destacamento", 42, tests=[("ENS-16", "Carbonatação")])],
               tests_map={"ENS-12": ["PACO"], "ENS-16": ["CARB"]})
    activities = by_service(plan)
    assert activities["PACO"]["activity_class"] == BASE
    assert activities["CARB"]["activity_class"] == CONDITIONAL
    assert "Destacamento" in activities["CARB"]["conditions"][0]
    assert activities["REL_ENS"]["activity_class"] == BASE


def test_ensaio_forte_sem_servico_gera_falha_critica():
    plan = run(candidates=[cand("PAT-BA-030", "Armaduras expostas", 84, tests=[("ENS-99", "Ensaio sem serviço")])])
    critical = [f for f in plan["flags"] if f["severity"] == "CRITICAL"]
    assert any(f["code"] == "UNMAPPED_ENSAIO" for f in critical)


def test_acesso_especial_por_pisos_ou_fachada():
    assert "ACESSO_ESP" in by_service(run({"storey_count": 13}))
    assert "ACESSO_ESP" not in by_service(run({"storey_count": 2}))
    assert "ACESSO_ESP" in by_service(run({"storey_count": 2}, raw="fissuras na fachada"))


def test_pedido_eletrico_nao_recebe_atividades_estruturais():
    plan = run({"categories": ["Diagnóstico elétrico"], "requested_services": ["Inspeção da rede elétrica"]},
               raw="quadro elétrico")
    assert set(by_service(plan)) == {"ELEC_INSPECT"}


def test_regra_com_servico_inexistente_e_sinalizada_e_ignorada():
    plan = run(rules=[*RULES, rule("R-X", "NAO_EXISTE", BASE, "ALWAYS")])
    assert "NAO_EXISTE" not in by_service(plan)
    assert {"kind": "regra", "code": "R-X", "name": "NAO_EXISTE", "pathology": ""} in plan["unmapped"]


def test_sem_atividade_base_e_falha_critica():
    plan = run(rules=[])
    assert [f["code"] for f in plan["flags"] if f["severity"] == "CRITICAL"] == ["NO_BASE_ACTIVITY"]


def test_resultado_e_deterministico():
    args = dict(fields={"storey_count": 6}, candidates=[cand("PAT-AL-001", "Fissuras", 56)])
    assert run(**args) == run(**args)


def test_linhas_da_proposta_condicionais_entram_no_total_e_texto_do_cliente_e_limpo():
    plan = run(candidates=[cand("PAT-AL-001", "Fissuras verticais", 56)])
    rows = {r["service_id"]: r for r in _item_rows(plan, CATALOG, "u1", "p1", existing_service_ids=set(), first_position=0)}
    assert all(r["enabled"] and not r["is_optional"] and r["included_in_approved_scope"] for r in rows.values())
    remocao = rows["REM_REVEST"]
    assert remocao["activity_class"] == CONDITIONAL and remocao["origin"] == "REQUIRES_REVIEW"
    assert "Preço a definir" not in remocao["technical_basis"] and "executada se" in remocao["technical_basis"]
    assert "R-AL-REV" in remocao["internal_note"] and "R-AL-REV" not in remocao["technical_basis"]
    assert rows["MOB"]["origin"] == "SUGGESTED" and rows["MOB"]["unit_price"] == 900


def test_nao_duplica_servicos_ja_existentes_na_proposta():
    plan = run(candidates=[cand("PAT-AL-001", "Fissuras", 56)])
    rows = _item_rows(plan, CATALOG, "u1", "p1", existing_service_ids={"MOB", "EST_VISUAL"}, first_position=5)
    assert "MOB" not in {r["service_id"] for r in rows}
    assert rows[0]["position"] == 5
