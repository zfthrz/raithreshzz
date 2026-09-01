from __future__ import annotations

from copy import deepcopy

from comparison_response_pipeline import build_validated_comparison_response


EPISODES = [{"episode_id": 1}, {"episode_id": 2}]


def _dependencies(*, episode_failure=False, validation_errors=None):
    def episode(metadata, comparison, item, output_dir):
        if episode_failure and item["episode_id"] == 2:
            return {
                "status": "REJECTED",
                "attempts": 2,
                "validation_errors": ["invalid"],
            }
        return {
            "status": "VALID",
            "attempts": item["episode_id"],
            "response": {"episode_id": item["episode_id"]},
            "fallback": "DETERMINISTIC",
        }

    def ranker(catalog, assessments, comparison, output_dir):
        return {
            "status": "VALID",
            "attempts": 1,
            "response": {
                "ordered_episode_ids": [1, 2],
                "priority_cut_rank": 1,
                "no_actionable_start_rank": None,
            },
        }

    def classify(assessments, catalog, response):
        return [dict(item, classification="PRIORITARIO") for item in assessments]

    def summary(assessments, catalog, comparison, output_dir):
        return {
            "status": "VALID",
            "attempts": 1,
            "response": {
                "comparison_observations": ["observación"],
                "limitations": [],
                "conclusion": "conclusión",
            },
            "fallback": "DETERMINISTIC",
        }

    return {
        "get_episode_response": episode,
        "get_ranker_response": ranker,
        "build_ranker_shadow": lambda catalog, response: {"status": "PASS"},
        "apply_classifications": classify,
        "get_summary_response": summary,
        "validate_response": lambda structured, catalog: validation_errors or [],
        "derive_classifications": lambda response, catalog: [
            {"episode_id": 1, "classification": "PRIORITARIO"},
            {"episode_id": 2, "classification": "SECUNDARIO"},
        ],
    }


def test_pipeline_builds_stable_valid_response_without_mutating_inputs():
    episodes = deepcopy(EPISODES)
    original = deepcopy(episodes)
    emitted = []

    result = build_validated_comparison_response(
        {}, {}, episodes, "debug", emit=emitted.append, **_dependencies()
    )

    assert episodes == original
    assert result["status"] == "VALID"
    assert result["attempts"] == 2
    assert result["response"] == {
        "episode_assessments": [
            {"episode_id": 1, "classification": "PRIORITARIO"},
            {"episode_id": 2, "classification": "PRIORITARIO"},
        ],
        "comparison_observations": ["observación"],
        "limitations": [],
        "conclusion": "conclusión",
    }
    assert result["audit"]["priority_ranking"]["ordered_episode_ids"] == [1, 2]
    assert result["audit"]["summary"]["fallback"] == "DETERMINISTIC"
    assert len(emitted) == 2


def test_pipeline_propagates_episode_rejection_without_running_later_stages():
    dependencies = _dependencies(episode_failure=True)
    dependencies["get_ranker_response"] = lambda *args: (_ for _ in ()).throw(
        AssertionError("ranker must not run")
    )

    result = build_validated_comparison_response(
        {}, {}, deepcopy(EPISODES), "debug", **dependencies
    )

    assert result["status"] == "REJECTED"
    assert result["attempts"] == 2
    assert result["validation_errors"] == ["Episodio 2: invalid"]
    assert len(result["audit"]["episodes"]) == 2


def test_pipeline_fails_closed_on_final_validation_errors():
    result = build_validated_comparison_response(
        {},
        {},
        deepcopy(EPISODES),
        "debug",
        **_dependencies(validation_errors=["contract mismatch"]),
    )

    assert result["status"] == "REJECTED"
    assert result["response"] is None
    assert result["validation_errors"] == ["contract mismatch"]
    assert "summary" in result["audit"]


def test_pipeline_keeps_shadow_failure_observational():
    dependencies = _dependencies()
    dependencies["build_ranker_shadow"] = lambda *args: (_ for _ in ()).throw(
        RuntimeError("shadow unavailable")
    )

    result = build_validated_comparison_response(
        {}, {}, deepcopy(EPISODES), "debug", **dependencies
    )

    assert result["status"] == "VALID"
    assert result["audit"]["priority_ranking"]["deterministic_shadow"] == {
        "status": "ERROR",
        "error": "shadow unavailable",
    }
