from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAIR_REVIEW_QUEUE = REPO_ROOT / "pair_review_queue.py"


def load_pair_review_queue():
    if not PAIR_REVIEW_QUEUE.is_file():
        raise FileNotFoundError(
            "No se encontró pair_review_queue.py en la raíz del repo: "
            f"{PAIR_REVIEW_QUEUE}"
        )

    spec = importlib.util.spec_from_file_location(
        "race_engineer_pair_review_queue_test_target",
        PAIR_REVIEW_QUEUE,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def sample_pair(
    session_a: int,
    episode_a: int,
    session_b: int,
    episode_b: int,
    center_diff: float,
    overlap: float,
    channel_jaccard: float,
):
    return {
        "track": "Test Track",
        "session_a": session_a,
        "session_b": session_b,
        "episode_pk_a": episode_a,
        "episode_pk_b": episode_b,
        "center_distance_abs_diff_m": center_diff,
        "overlap_over_union": overlap,
        "channel_jaccard": channel_jaccard,
        "action_time_loss_similarity": 0.5,
    }


def test_pair_id_is_order_independent():
    module = load_pair_review_queue()

    a = sample_pair(
        1,
        10,
        2,
        20,
        5.0,
        0.9,
        1.0,
    )

    b = sample_pair(
        2,
        20,
        1,
        10,
        5.0,
        0.9,
        1.0,
    )

    assert module.stable_pair_id(a) == module.stable_pair_id(b)


def test_queue_selection_does_not_add_labels():
    module = load_pair_review_queue()

    pairs = [
        sample_pair(
            1,
            10,
            2,
            20,
            5.0,
            0.9,
            1.0,
        ),
        sample_pair(
            1,
            11,
            3,
            30,
            50.0,
            0.1,
            0.0,
        ),
        sample_pair(
            2,
            21,
            3,
            31,
            15.0,
            0.5,
            0.5,
        ),
    ]

    for pair in pairs:
        pair["pair_id"] = module.stable_pair_id(pair)

    queue = module.select_queue(
        pairs,
        per_lens=2,
        max_total=None,
        seed=123,
    )

    assert queue

    for item in queue:
        assert "human_label" not in item
        assert "match_status" not in item
        assert "selected_by" in item
