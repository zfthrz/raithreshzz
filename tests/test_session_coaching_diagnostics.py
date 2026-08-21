
from tools.session_coaching_diagnostics import diagnose_payload, aggregate_sessions

def item(label, family, rank, repeated=False):
    return {"plan_label":label,"_p9_presentation_metadata":{
        "primary_action_family":family,
        "original_plan_rank":rank,
        "presentation_rank":rank,
        "redundancy_status":"REPEATED_FAMILY" if repeated else "FIRST_OCCURRENCE"}}

def payload(track="Imola", focus=("A","B"), reordered=False):
    items=[item("A","THROTTLE_TIMING",0),item("B","BRAKE_TIMING",1),item("C","BRAKE_TIMING",2,True)]
    by={x["plan_label"]:x for x in items}
    f=[by[x] for x in focus]
    return {
        "metadata":{"track":track,"model":"deepseek-v4-pro","structured_validation":"PASS","factual_grounding_validation":"PASS"},
        "next_stint_plan":items,
        "next_stint_plan_presentation":{"presentation":items,"_p10_presentation":{"status":"ACTIVE","reordered":reordered}},
        "next_stint_focus":{"status":"ACTIVE","items":f,"focus_count":len(f)},
    }

def test_extracts_families():
    d=diagnose_payload(payload())
    assert d.focus_families==["THROTTLE_TIMING","BRAKE_TIMING"]

def test_counts_repeated():
    assert diagnose_payload(payload()).repeated_family_count==1

def test_diverse_focus():
    d=diagnose_payload(payload())
    assert d.focus_count==2 and d.distinct_focus_family_count==2

def test_duplicate_focus():
    assert diagnose_payload(payload(focus=("B","C"))).distinct_focus_family_count==1

def test_aggregate_diversity():
    a=aggregate_sessions([diagnose_payload(payload()), diagnose_payload(payload("Fuji",("B","C")))])
    assert a["p11"]["two_focus_diversity_rate"]==0.5

def test_slot_counts():
    a=aggregate_sessions([diagnose_payload(payload())])
    assert a["family_counts"]["focus_slots"]["slot_1"]=={"THROTTLE_TIMING":1}
    assert a["family_counts"]["focus_slots"]["slot_2"]=={"BRAKE_TIMING":1}

def test_reordered_rate():
    a=aggregate_sessions([diagnose_payload(payload(reordered=True)),diagnose_payload(payload("Fuji"))])
    assert a["p10"]["reordered_rate"]==0.5

def test_track_breakdown():
    a=aggregate_sessions([diagnose_payload(payload("Imola")),diagnose_payload(payload("Fuji"))])
    assert a["tracks"]["Imola"]["session_count"]==1
    assert a["tracks"]["Fuji"]["session_count"]==1
