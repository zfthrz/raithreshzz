import copy
import importlib


MODULE_NAME = "llm_analysis_deepseek"


def _module():
    return importlib.import_module(MODULE_NAME)


def _episode(
    episode_id,
    *,
    global_rank,
    evidence="moderate",
    loss=0.05,
    channels=1,
    length_m=25.0,
):
    return {
        "episode_id": episode_id,
        "global_rank": global_rank,
        "action_time_loss_s": loss,
        "evidence_strength": evidence,
        "action_channel_count": channels,
        "length_m": length_m,
    }


def _shadow(episodes, llm_response):
    return _module().build_deterministic_ranker_shadow_audit(
        episodes,
        llm_response,
    )


def test_shadow_reports_full_agreement():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="moderate"),
    ]
    llm_response = {
        "ordered_episode_ids": [1, 2],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }

    audit = _shadow(episodes, llm_response)

    assert audit["status"] == "VALID"
    assert audit["response"] == llm_response
    assert audit["agreement"] == {
        "ordered_episode_ids": True,
        "priority_cut_rank": True,
        "no_actionable_start_rank": True,
        "classifications": True,
        "full": True,
    }
    assert (
        audit["llm_classifications"]
        == audit["deterministic_classifications"]
    )


def test_shadow_detects_order_only_disagreement():
    episodes = [
        _episode(1, global_rank=1, evidence="moderate"),
        _episode(2, global_rank=2, evidence="moderate"),
    ]
    llm_response = {
        "ordered_episode_ids": [2, 1],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }

    audit = _shadow(episodes, llm_response)

    assert audit["agreement"]["ordered_episode_ids"] is False
    assert audit["agreement"]["priority_cut_rank"] is True
    assert audit["agreement"]["no_actionable_start_rank"] is True
    assert audit["agreement"]["classifications"] is False
    assert audit["agreement"]["full"] is False


def test_shadow_detects_priority_cut_disagreement():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="strong"),
        _episode(3, global_rank=3, evidence="moderate"),
    ]
    llm_response = {
        "ordered_episode_ids": [1, 2, 3],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 4,
    }

    audit = _shadow(episodes, llm_response)

    assert audit["response"]["priority_cut_rank"] == 2
    assert audit["agreement"]["ordered_episode_ids"] is True
    assert audit["agreement"]["priority_cut_rank"] is False
    assert audit["agreement"]["no_actionable_start_rank"] is True
    assert audit["agreement"]["classifications"] is False
    assert audit["agreement"]["full"] is False


def test_shadow_detects_no_actionable_cut_disagreement():
    episodes = [
        _episode(1, global_rank=1, evidence="moderate"),
        _episode(2, global_rank=2, evidence="moderate"),
        _episode(3, global_rank=3, evidence="weak"),
    ]
    llm_response = {
        "ordered_episode_ids": [1, 2, 3],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 4,
    }

    audit = _shadow(episodes, llm_response)

    assert audit["response"]["no_actionable_start_rank"] == 3
    assert audit["agreement"]["ordered_episode_ids"] is True
    assert audit["agreement"]["priority_cut_rank"] is True
    assert audit["agreement"]["no_actionable_start_rank"] is False
    assert audit["agreement"]["classifications"] is False
    assert audit["agreement"]["full"] is False


def test_shadow_keeps_complete_classification_lists_for_diagnostics():
    episodes = [
        _episode(10, global_rank=1, evidence="moderate"),
        _episode(20, global_rank=2, evidence="moderate"),
    ]
    llm_response = {
        "ordered_episode_ids": [20, 10],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }

    audit = _shadow(episodes, llm_response)

    assert audit["llm_classifications"] == [
        {
            "episode_id": 10,
            "relative_priority_rank": 2,
            "classification": "SECUNDARIO",
        },
        {
            "episode_id": 20,
            "relative_priority_rank": 1,
            "classification": "PRIORITARIO",
        },
    ]
    assert audit["deterministic_classifications"] == [
        {
            "episode_id": 10,
            "relative_priority_rank": 1,
            "classification": "PRIORITARIO",
        },
        {
            "episode_id": 20,
            "relative_priority_rank": 2,
            "classification": "SECUNDARIO",
        },
    ]


def test_shadow_does_not_mutate_inputs():
    episodes = [
        _episode(1, global_rank=1, evidence="strong"),
        _episode(2, global_rank=2, evidence="moderate"),
    ]
    llm_response = {
        "ordered_episode_ids": [1, 2],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }
    episodes_before = copy.deepcopy(episodes)
    llm_before = copy.deepcopy(llm_response)

    _shadow(episodes, llm_response)

    assert episodes == episodes_before
    assert llm_response == llm_before


def test_deterministic_shadow_response_always_passes_ranker_validator():
    module = _module()
    catalogs = [
        [
            _episode(1, global_rank=1, evidence="moderate"),
        ],
        [
            _episode(1, global_rank=1, evidence="strong"),
            _episode(2, global_rank=2, evidence="moderate"),
        ],
        [
            _episode(1, global_rank=1, evidence="strong"),
            _episode(2, global_rank=2, evidence="strong"),
            _episode(3, global_rank=3, evidence="weak"),
        ],
    ]

    for episodes in catalogs:
        response = module.build_deterministic_comparison_ranker_response(
            episodes
        )
        assert module.validate_comparison_ranker_response(
            response,
            episodes,
        ) == []


def test_runtime_keeps_llm_ranker_as_production_authority(monkeypatch, tmp_path):
    module = _module()
    episodes = [
        _episode(1, global_rank=1, evidence="moderate"),
        _episode(2, global_rank=2, evidence="moderate"),
    ]

    episode_responses = {
        1: {
            "episode_id": 1,
            "interpretation": "episodio uno",
            "hypotheses": [],
            "recommendation": "acción uno",
        },
        2: {
            "episode_id": 2,
            "interpretation": "episodio dos",
            "hypotheses": [],
            "recommendation": "acción dos",
        },
    }

    def fake_episode_response(_metadata, _comparison, episode, _output_dir):
        return {
            "status": "VALID",
            "attempts": 1,
            "response": copy.deepcopy(
                episode_responses[episode["episode_id"]]
            ),
            "validation_errors": [],
        }

    llm_ranker_response = {
        "ordered_episode_ids": [2, 1],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }

    monkeypatch.setattr(
        module,
        "get_validated_episode_response",
        fake_episode_response,
    )
    monkeypatch.setattr(
        module,
        "get_validated_comparison_ranker_response",
        lambda *_args, **_kwargs: {
            "status": "VALID",
            "attempts": 1,
            "response": copy.deepcopy(llm_ranker_response),
            "validation_errors": [],
        },
    )
    monkeypatch.setattr(
        module,
        "get_validated_comparison_summary_response",
        lambda *_args, **_kwargs: {
            "status": "VALID",
            "attempts": 1,
            "response": {
                "comparison_observations": [],
                "limitations": [],
                "conclusion": "síntesis",
            },
            "validation_errors": [],
        },
    )
    monkeypatch.setattr(
        module,
        "validate_comparison_llm_response",
        lambda *_args, **_kwargs: [],
    )

    result = module.get_validated_comparison_response(
        metadata={},
        comparison={
            "reference_lap": 1,
            "comparison_lap": 2,
        },
        episode_catalog=episodes,
        output_dir=str(tmp_path),
    )

    assert result["status"] == "VALID"

    classifications = {
        item["episode_id"]: item["classification"]
        for item in result["response"]["episode_assessments"]
    }
    assert classifications == {
        1: "SECUNDARIO",
        2: "PRIORITARIO",
    }

    shadow = result["audit"]["priority_ranking"][
        "deterministic_shadow"
    ]
    assert shadow["response"]["ordered_episode_ids"] == [1, 2]
    assert shadow["agreement"]["ordered_episode_ids"] is False
    assert shadow["agreement"]["classifications"] is False
    assert shadow["agreement"]["full"] is False

def test_runtime_shadow_failure_does_not_block_production(monkeypatch, tmp_path):
    module = _module()
    episodes = [
        _episode(1, global_rank=1, evidence="moderate"),
        _episode(2, global_rank=2, evidence="moderate"),
    ]

    def fake_episode_response(_metadata, _comparison, episode, _output_dir):
        return {
            "status": "VALID",
            "attempts": 1,
            "response": {
                "episode_id": episode["episode_id"],
                "interpretation": f"episodio {episode['episode_id']}",
                "hypotheses": [],
                "recommendation": f"acción {episode['episode_id']}",
            },
            "validation_errors": [],
        }

    llm_ranker_response = {
        "ordered_episode_ids": [1, 2],
        "priority_cut_rank": 1,
        "no_actionable_start_rank": 3,
    }

    monkeypatch.setattr(
        module,
        "get_validated_episode_response",
        fake_episode_response,
    )
    monkeypatch.setattr(
        module,
        "get_validated_comparison_ranker_response",
        lambda *_args, **_kwargs: {
            "status": "VALID",
            "attempts": 1,
            "response": copy.deepcopy(llm_ranker_response),
            "validation_errors": [],
        },
    )
    monkeypatch.setattr(
        module,
        "build_deterministic_ranker_shadow_audit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("shadow roto")
        ),
    )
    monkeypatch.setattr(
        module,
        "get_validated_comparison_summary_response",
        lambda *_args, **_kwargs: {
            "status": "VALID",
            "attempts": 1,
            "response": {
                "comparison_observations": [],
                "limitations": [],
                "conclusion": "síntesis",
            },
            "validation_errors": [],
        },
    )
    monkeypatch.setattr(
        module,
        "validate_comparison_llm_response",
        lambda *_args, **_kwargs: [],
    )

    result = module.get_validated_comparison_response(
        metadata={},
        comparison={
            "reference_lap": 1,
            "comparison_lap": 2,
        },
        episode_catalog=episodes,
        output_dir=str(tmp_path),
    )

    assert result["status"] == "VALID"
    shadow = result["audit"]["priority_ranking"][
        "deterministic_shadow"
    ]
    assert shadow == {
        "status": "ERROR",
        "error": "shadow roto",
    }

    classifications = {
        item["episode_id"]: item["classification"]
        for item in result["response"]["episode_assessments"]
    }
    assert classifications == {
        1: "PRIORITARIO",
        2: "SECUNDARIO",
    }
