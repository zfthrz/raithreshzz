
from coaching_precision import build_track_reference_rows


def _profile():
    return {
        "status": "VALIDATED_MULTI_SESSION",
        "turns": [
            {"turn": 1, "name": "'S' do Senna", "start_m": 0, "apex_m": 10, "end_m": 20},
            {"turn": 8, "name": "Pinheirinho", "start_m": 100, "apex_m": 110, "end_m": 120},
            {"turn": 10, "name": "Bico de Pato", "start_m": 200, "apex_m": 210, "end_m": 220},
        ],
    }


def _location(turn, label):
    return {
        "status": "RESOLVED",
        "label": label,
        "overlaps": [{"turn": turn, "overlap_m": 20.0, "overlap_share": 1.0}],
    }


def _zones_by_turn(rows):
    result = {}
    for row in rows:
        for turn in range(row["start_turn"], row["end_turn"] + 1):
            result[turn] = list(row["plan_zones"])
    return result


def test_explicit_plan_labels_survive_presentation_reordering():
    plan = [
        {"plan_label": "A", "track_location": _location(10, "T10 — Bico de Pato")},
        {"plan_label": "C", "track_location": _location(1, "T1 — 'S' do Senna")},
        {"plan_label": "B", "track_location": _location(8, "T8 — Pinheirinho")},
    ]
    zones = _zones_by_turn(build_track_reference_rows(_profile(), plan))
    assert zones[10] == ["ZONA A"]
    assert zones[1] == ["ZONA C"]
    assert zones[8] == ["ZONA B"]


def test_legacy_plan_without_labels_keeps_positional_fallback():
    plan = [
        {"track_location": _location(10, "T10 — Bico de Pato")},
        {"track_location": _location(8, "T8 — Pinheirinho")},
        {"track_location": _location(1, "T1 — 'S' do Senna")},
    ]
    zones = _zones_by_turn(build_track_reference_rows(_profile(), plan))
    assert zones[10] == ["ZONA A"]
    assert zones[8] == ["ZONA B"]
    assert zones[1] == ["ZONA C"]


def test_invalid_plan_label_falls_back_positionally():
    plan = [{"plan_label": "AA", "track_location": _location(10, "T10 — Bico de Pato")}]
    zones = _zones_by_turn(build_track_reference_rows(_profile(), plan))
    assert zones[10] == ["ZONA A"]
