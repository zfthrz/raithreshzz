import copy
from tools.audit_coaching_output import audit_payload

def payload():
    def item(label, family, rank):
        return {"plan_label": label, "driver_cues":[{"text":label}],
                "_p9_presentation_metadata":{"primary_action_family":family,
                "original_plan_rank":rank,"presentation_rank":rank,
                "redundancy_status":"FIRST_OCCURRENCE" if rank < 2 else "REPEATED_FAMILY"}}
    a,b,c = item("A","THROTTLE_TIMING",0), item("B","BRAKE_TIMING",1), item("C","BRAKE_TIMING",2)
    return {"metadata":{"structured_validation":"PASS","factual_grounding_validation":"PASS","track":"Imola","reference_lap":5},
            "next_stint_plan":[copy.deepcopy(a),copy.deepcopy(b),copy.deepcopy(c)],
            "next_stint_plan_presentation":{"presentation":[copy.deepcopy(a),copy.deepcopy(b),copy.deepcopy(c)],
                "_p10_presentation":{"status":"ACTIVE","item_count":3}},
            "next_stint_focus":{"status":"ACTIVE","focus_count":2,"items":[copy.deepcopy(a),copy.deepcopy(b)]}}

def codes(r): return {x.code for x in r.issues if x.severity=="ERROR"}
def test_valid(): assert audit_payload(payload()).status=="PASS"
def test_bad_prefix():
    p=payload(); p["next_stint_focus"]["items"].reverse()
    assert "P11_NOT_P10_PREFIX" in codes(audit_payload(p))
def test_too_many():
    p=payload(); p["next_stint_focus"]["items"]=copy.deepcopy(p["next_stint_plan"]); p["next_stint_focus"]["focus_count"]=3
    assert "P11_TOO_MANY_ITEMS" in codes(audit_payload(p))
def test_bad_rank():
    p=payload(); p["next_stint_plan_presentation"]["presentation"][2]["_p9_presentation_metadata"]["presentation_rank"]=9
    assert "P10_PRESENTATION_RANK_INVALID" in codes(audit_payload(p))
def test_validation_fail():
    p=payload(); p["metadata"]["structured_validation"]="FAIL"
    assert "STRUCTURED_VALIDATION_NOT_PASS" in codes(audit_payload(p))
def test_missing_p11_warning_only():
    p=payload(); p.pop("next_stint_focus"); r=audit_payload(p)
    assert r.status=="PASS" and any(x.code=="P11_MISSING" for x in r.issues)
