import re
from app.services import field_activities as fa
from app.proposal_library import _dedupe_similar_references

CAT = {k: {"service_id": k, "name": k, "unit": "un", "selling_price": p, "category": c, "technical_basis": ""}
       for k, p, c in [("INSP", 100, "VIS"), ("MAP", 50, "VIS"), ("HUM", 80, "NDT"), ("OPEN", 200, "DEST"),
                       ("REPOS", 120, "DEST"), ("SEMPRECO", None, "VIS"), ("ZERO", 0, "VIS"), ("REL_ENS", 90, "REL")]}

def plan(rules=(), deps=(), cands=(), s2t=None):
    return fa.plan_field_activities(fields={"_dependencies": list(deps)}, rules=list(rules), catalog=CAT,
                                    services_by_test=s2t or {}, candidates=list(cands))
def cls(p): return {a["service_id"]: a["activity_class"] for a in p["activities"]}

def test_A_rag_forte_nao_cria_base():
    c = [{"code": "PAT-HU-002", "name": "Infiltração", "match_percent": 96, "tests": [{"code": "T1", "name": "x"}], "solutions": []}]
    p = plan(cands=c, s2t={"T1": ["HUM"]})
    assert cls(p)["HUM"] == "CONDITIONAL"
    a = next(x for x in p["activities"] if x["service_id"] == "HUM")
    assert a["conditions"] and a["technical_basis"]

def test_regra_base_continua_base_com_rag():
    c = [{"code": "PAT-HU-002", "name": "I", "match_percent": 10, "tests": ["T1"]}]
    p = plan(rules=[{"service_id": "HUM", "activity_class": "BASE"}], cands=c, s2t={"T1": ["HUM"]})
    assert cls(p)["HUM"] == "BASE"

def test_C_F_dependencia_herda_condicional():
    rules = [{"service_id": "OPEN", "activity_class": "CONDITIONAL", "trigger_condition": "Se houver indício de infiltração interna"}]
    deps = [{"service_id": "OPEN", "followup_service_id": "REPOS", "relation": "REPOSICAO", "quantity_ratio": 1, "note": "Repor a área aberta"}]
    p = plan(rules=rules, deps=deps)
    c = cls(p)
    assert c["OPEN"] == "CONDITIONAL" and c["REPOS"] == "CONDITIONAL"
    repos = next(a for a in p["activities"] if a["service_id"] == "REPOS")
    assert "Se houver indício de infiltração interna" in repos["conditions"][0]

def test_dependencia_nao_promove_nem_apaga_condicoes():
    rules = [{"service_id": "INSP", "activity_class": "BASE"},
             {"service_id": "REPOS", "activity_class": "CONDITIONAL", "trigger_condition": "Condição própria"}]
    deps = [{"service_id": "INSP", "followup_service_id": "REPOS", "note": "n"}]
    p = plan(rules=rules, deps=deps)
    repos = next(a for a in p["activities"] if a["service_id"] == "REPOS")
    assert repos["activity_class"] == "CONDITIONAL" and "Condição própria" in repos["conditions"]

def test_dependencias_repetidas_e_ciclo():
    rules = [{"service_id": "INSP", "activity_class": "BASE"}]
    deps = [{"service_id": "INSP", "followup_service_id": "MAP"}, {"service_id": "MAP", "followup_service_id": "INSP"},
            {"service_id": "INSP", "followup_service_id": "MAP"}]
    p = plan(rules=rules, deps=deps)
    assert sorted(cls(p)) == ["INSP", "MAP"]
    assert any(f["code"] == "DEPENDENCY_CYCLE" for f in p["flags"])

def test_cadeia_transitiva_ordem():
    rules = [{"service_id": "OPEN", "activity_class": "CONDITIONAL", "trigger_condition": "X"}]
    deps = [{"service_id": "REPOS", "followup_service_id": "MAP"}, {"service_id": "OPEN", "followup_service_id": "REPOS"}]
    c = cls(plan(rules=rules, deps=deps))
    assert c == {"OPEN": "CONDITIONAL", "REPOS": "CONDITIONAL", "MAP": "CONDITIONAL"}

def test_D_preco():
    assert fa._price_info(CAT["SEMPRECO"]) == (0.0, "UNKNOWN")
    assert fa._price_info(CAT["ZERO"]) == (0.0, "ZERO_IN_CATALOG")
    assert fa._price_info(CAT["INSP"]) == (100.0, "CATALOG")
    acts = [{"service_id": s, "name": s, "quantity": 1, "activity_class": "BASE"} for s in ("INSP", "SEMPRECO", "ZERO")]
    rows = {r["service_id"]: r for r in fa._item_rows("p1", acts, CAT)}
    assert rows["INSP"]["origin"] == "SUGGESTED"
    assert rows["SEMPRECO"]["origin"] == "REQUIRES_REVIEW" and "PREÇO POR VALIDAR" in rows["SEMPRECO"]["internal_note"]
    assert rows["ZERO"]["origin"] == "REQUIRES_REVIEW"

def test_E_hipotese_ligada_a_patologia():
    c = [{"code": "PAT-HU-002", "name": "I", "evidence": ["fissuras com humidade"], "tests": [],
          "solutions": [{"code": "SOL-1", "name": "Impermeabilização"}, "texto sem código"]}]
    h = plan(cands=c)["hypotheses"]
    assert h[0]["pathology_code"] == "PAT-HU-002" and h[0]["code"] == "SOL-1"
    assert h[0]["_candidate_evidence"] == ["fissuras com humidade"]

def test_6_duracao():
    rules = {"S": [{"minimum_quantity": 1, "maximum_quantity": 2, "duration_minutes": 60, "team_size": 1, "priority": 1},
                   {"minimum_quantity": 10, "maximum_quantity": 20, "duration_minutes": 300, "team_size": 3, "priority": 1}]}
    r, chk = fa._select_duration_rule("S", rules, 1)
    assert r["duration_minutes"] == 60 and r["team_size"] == 1 and not chk
    assert fa._select_duration_rule("S", rules, 5)[0] is None  # nenhuma regra aplica-se


def test_relatorio_de_ensaios_usa_o_servico_REL_ENS_do_catalogo():
    assert fa.REPORT_SERVICE_ID == "REL_ENS"
    c = [{"code": "PAT-HU-002", "name": "I", "match_percent": 50, "tests": ["T1"]}]
    assert cls(plan(cands=c, s2t={"T1": ["HUM"]}))["REL_ENS"] == "BASE"


def test_texto_do_cliente_sem_notas_internas():
    cat = {**CAT, "OPEN": {**CAT["OPEN"], "technical_basis": "Abertura pontual. Preço a definir pelo engenheiro."}}
    rules = [{"code": "R1", "service_id": "OPEN", "activity_class": "CONDITIONAL",
              "trigger_condition": "for necessário ver o interior", "technical_notes": "Regra inicial: validar pelo engenheiro."}]
    p = fa.plan_field_activities(fields={"_dependencies": []}, rules=rules, catalog=cat, services_by_test={}, candidates=[])
    a = fa._enrich_plan_activities(p["activities"], catalog=cat, procedures_by_service={}, procedures_by_id={},
                                   procedure_resources_by_procedure={}, activity_resources_by_service={},
                                   resources_by_id={}, duration_rules_by_service={})
    row = fa._item_rows("p1", a, cat)[0]
    assert "Preço a definir" not in row["technical_basis"] and "validar pelo engenheiro" not in row["technical_basis"]
    assert "for necessário ver o interior" in row["technical_basis"]
    assert "Regra inicial" in row["internal_note"]


def test_G_propostas_anteriores_quase_iguais_ficam_agrupadas():
    base = {"title": "Diagnóstico fissuras fachada noroeste", "summary": "inspeção fissuras fachada humidade infiltração parede"}
    scored = [{**base, "id": "1", "request_id": "a", "match_percent": 93},
              {**base, "id": "2", "request_id": "b", "match_percent": 93},
              {**base, "id": "3", "request_id": "c", "match_percent": 93},
              {"title": "Ensaios de carbonatação em pilares", "summary": "carbonatação cloretos betão pilares laje", "id": "4",
               "request_id": "d", "match_percent": 60}]
    r = _dedupe_similar_references(scored)
    assert [x["id"] for x in r] == ["1", "4"]
    assert r[0]["duplicates_hidden"] == 2 and r[1]["duplicates_hidden"] == 0
