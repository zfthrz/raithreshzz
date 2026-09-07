from __future__ import annotations

import copy
import json

import pytest

import deterministic_debrief_output as output
from debrief_english import (
    build_english_presentation,
    cue_text,
    observation_text,
    temporal_text,
    validate_presentation,
)
from debrief_language import load_debrief_language, save_debrief_language
from race_engineer_gui import (
    action_only_debrief_markdown,
    compact_debrief_markdown,
    debrief_markdown_line,
    debrief_section_jumps,
)
from race_engineer_track_map import load_track_priorities


def document():
    return {
        "metadata": {"track": "Imola", "reference_lap": 3},
        "comparisons": [{"reference_lap": 3, "comparison_lap": 4,
                         "comparison_minus_reference_s": 0.35,
                         "session_plan_eligible": True}],
        "global_analysis": "Texto canónico español",
        "global_structured": {},
        "session_coaching_facts": {
            "next_stint_focus": {"status": "ACTIVE", "focus_count": 1,
                                 "items": [{"plan_label": "B"}]},
            "next_stint_plan": [
                {"plan_label": "B", "start_distance_m": 100, "end_distance_m": 180,
                 "track_location": {"status": "RESOLVED", "label": "T2 — Tamburello"},
                 "comparison_count": 2, "comparisons": ["3->4", "3->5"],
                 "quantitative_observations": ["más freno: promedio +13.6 pp; pico +18.3 pp"],
                 "driver_cues": [
                     {"kind": "spatial_points", "channel": "brake",
                      "text": "frená aproximadamente 8 m más tarde (referencia: ~30 m antes de T2 — Tamburello)"},
                     {"kind": "repeated_steering_secondary", "channel": "steering_magnitude",
                      "text": "reducí la magnitud del volante hacia la referencia",
                      "secondary_only": True},
                 ]},
                {"plan_label": "A", "start_distance_m": 300, "end_distance_m": 400,
                 "driver_cues": [{"kind": "qualitative_reference_level", "text": "aumentá el acelerador"}]},
            ],
        },
    }


def test_language_preference_is_local_and_invalid_values_fall_back(tmp_path):
    path = tmp_path / "preferences.json"
    assert load_debrief_language(path) == "es"
    save_debrief_language("en", path)
    assert load_debrief_language(path) == "en"
    with pytest.raises(ValueError):
        save_debrief_language("fr", path)
    assert load_debrief_language(path) == "en"
    for invalid in ("{", "[]", '{"language":"other"}'):
        path.write_text(invalid)
        assert load_debrief_language(path) == "es"


@pytest.mark.parametrize(("source", "expected"), [
    ("frená aproximadamente 8 m más tarde", "brake approximately 8 m later"),
    ("soltá el freno aproximadamente 11 m más temprano", "release the brake approximately 11 m earlier"),
    ("reaplicá el acelerador aproximadamente 2 m más tarde", "reapply the throttle approximately 2 m later"),
    ("soltá el acelerador aproximadamente 6 m más temprano", "release the throttle approximately 6 m earlier"),
    ("reducí el freno y aumentá el acelerador", "reduce brake input and increase throttle input"),
    ("reaplicá y sostené el acelerador como en la referencia", "reapply and hold the throttle as in the reference"),
    ("replicá la secuencia de freno de la referencia: aplicación alta de freno → freno liberado", "match the reference brake sequence: high brake application → brake released"),
])
def test_authorized_action_direction_numbers_and_order_are_preserved(source, expected):
    assert cue_text(source) == expected


def test_unknown_wording_never_becomes_new_coaching():
    with pytest.raises(ValueError):
        cue_text("acelerá a 200 km/h")
    with pytest.raises(ValueError):
        cue_text("replicá la secuencia de freno de la referencia: forma desconocida")


def test_english_projection_preserves_source_and_complete_plan():
    source = document()
    before = copy.deepcopy(source)
    english = build_english_presentation(source)
    assert source == before
    assert [p["plan_label"] for p in english["plan"]] == ["B", "A"]
    assert [len(p["cues"]) for p in english["plan"]] == [2, 1]
    assert "8 m later" in english["global_analysis"]
    assert "~30 m before T2 — Tamburello" in english["global_analysis"]
    assert "+13.6 pp; peak +18.3 pp" in english["global_analysis"]
    assert "steering magnitude towards the reference" in english["global_analysis"]


def test_bilingual_readers_keep_actions_and_section_targets():
    markdown = build_english_presentation(document())["global_analysis"]
    checklist = action_only_debrief_markdown(markdown)
    assert checklist.count("### ") == 2
    assert "**Action · Second cue:**" in checklist
    assert "**Evidence" not in checklist and "**Context" not in checklist
    assert "Technical support" not in checklist
    assert [x[0] for x in debrief_section_jumps(markdown)] == ["Start", "Focus", "Plan", "Support"]
    assert "## Session summary" in compact_debrief_markdown(markdown)
    assert debrief_markdown_line("**Action · What to change:** Brake.")[0] == "debrief_action"


@pytest.mark.parametrize("tamper", ["text", "order", "direction", "missing", "language"])
def test_localized_presentation_rejects_tampering(tamper):
    source = document()
    source["metadata"]["debrief_language"] = "en"
    source["localized_presentation"] = build_english_presentation(source)
    validate_presentation(source)
    if tamper == "text":
        source["localized_presentation"]["global_analysis"] += "\nDrive faster."
    elif tamper == "order":
        source["localized_presentation"]["plan"].reverse()
    elif tamper == "direction":
        source["localized_presentation"]["plan"][0]["cues"][0]["text"] = "brake earlier"
    elif tamper == "missing":
        source.pop("localized_presentation")
    else:
        source["metadata"]["debrief_language"] = "fr"
    with pytest.raises(ValueError):
        validate_presentation(source)


def test_telemetry_uses_localized_cues_without_changing_intervals(tmp_path):
    source = document()
    path = tmp_path / "debrief.json"
    path.write_text(json.dumps(source))
    spanish = load_track_priorities(path)
    source["metadata"]["debrief_language"] = "en"
    source["localized_presentation"] = build_english_presentation(source)
    path.write_text(json.dumps(source))
    english = load_track_priorities(path)
    assert [(p.priority_id, p.start_distance_m, p.end_distance_m, p.is_focus, p.has_validated_steering) for p in english] == [(p.priority_id, p.start_distance_m, p.end_distance_m, p.is_focus, p.has_validated_steering) for p in spanish]
    assert english[0].cues[0].startswith("brake approximately 8 m later")


def test_new_english_output_and_existing_spanish_language_are_independent(monkeypatch, tmp_path):
    destination = tmp_path / "debrief.json"
    monkeypatch.setattr(output, "compatible_debrief_output_path", lambda *a, **k: (destination, tmp_path))
    monkeypatch.setattr(output, "load_debrief_language", lambda: "en")
    d = document()
    def save(language=None):
        return output.save_compatible_debrief("source.json", d["metadata"], d["comparisons"], d["session_coaching_facts"], {}, d["global_analysis"], model_name="deterministic_debrief", usage_summary={}, context_size=0, temperature=0, anomaly_gate_config={}, language=language)
    save()
    english = json.loads(destination.read_text(encoding="utf-8"))
    assert english["metadata"]["debrief_language"] == "en"
    validate_presentation(english)
    # A legacy Spanish artifact keeps its language even after the preference changes.
    destination.write_text(json.dumps(d))
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="existing debrief"):
        save("en")
    assert destination.read_bytes() == before
    save()
    spanish = json.loads(destination.read_text(encoding="utf-8"))
    assert spanish["metadata"]["debrief_language"] == "es"
    assert spanish["global_analysis"] == d["global_analysis"]
    assert "localized_presentation" not in spanish


def test_temporal_context_preserves_numbers_and_never_becomes_action():
    source = "se repitió la secuencia freno → acelerador sin solapamiento en 3 comparaciones; separación entre eventos de 12 a 28 m"
    assert temporal_text(source) == "the brake → throttle sequence repeated without overlap in 3 comparisons; separation between events from 12 to 28 m"
    assert observation_text("menos acelerador") == "less throttle input"


def test_new_report_validator_uses_exact_neutral_renderer(monkeypatch):
    import validate_llm_analysis_output as validator
    from deterministic_global_render import render_global_analysis
    source = document()
    source["metadata"]["report_presentation_version"] = "2.5"
    monkeypatch.setattr(validator.llm_renderer, "load_track_location_context", lambda _: {})
    monkeypatch.setattr(validator.llm_renderer, "render_track_reference_section", lambda *a: "")
    source["global_analysis"] = render_global_analysis(source["metadata"], source["comparisons"], source["session_coaching_facts"], {})
    errors = []
    validator.validate_global_render(source, errors)
    assert errors == []
    source["global_analysis"] += "\nUna acción inventada."
    validator.validate_global_render(source, errors)
    assert any("no coincide exactamente" in error for error in errors)


def test_focus_preserves_p11_order_and_inconsistent_focus_falls_back():
    source = document()
    focus = source["session_coaching_facts"]["next_stint_focus"]
    focus.update(focus_count=2, items=[{"plan_label": "A"}, {"plan_label": "B"}])
    text = build_english_presentation(source)["global_analysis"]
    assert text.index("- Zone A") < text.index("- Zone B")
    focus["focus_count"] = 1
    text = build_english_presentation(source)["global_analysis"]
    assert text.index("- Zone B") < text.index("- Zone A")


def test_combined_sequence_keeps_every_authorized_event_in_order():
    source = document()
    cue = source["session_coaching_facts"]["next_stint_plan"][0]["driver_cues"][0]
    cue.update(kind="combined_spatial_sequence", text="soltá el acelerador aproximadamente 12 m más temprano; después, frená aproximadamente 8 m más tarde",
               coaching_sequence={"status": "COMBINED", "events": [
                   {"text": "soltá el acelerador aproximadamente 12 m más temprano"},
                   {"text": "frená aproximadamente 8 m más tarde"}]})
    text = build_english_presentation(source)["global_analysis"]
    checklist = action_only_debrief_markdown(text)
    assert "1. Release the throttle approximately 12 m earlier." in checklist
    assert "2. Brake approximately 8 m later." in checklist
    assert checklist.index("1. Release") < checklist.index("2. Brake")
