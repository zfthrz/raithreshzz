from pathlib import Path
import argparse
import importlib.util
import sys
import tempfile

import numpy as np
import pandas as pd


SUITE_VERSION = "1.1"


class RegressionFailure(Exception):
    pass


class Runner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def pass_(self, label):
        self.passed += 1
        print(f"  PASS  {label}")

    def fail(self, label, exc):
        self.failed += 1
        print(f"  FAIL  {label}")
        print(f"        {exc}")

    def skip(self, label, reason):
        self.skipped += 1
        print(f"  SKIP  {label}")
        print(f"        {reason}")

    def run(self, label, func):
        try:
            func()
        except Exception as exc:
            self.fail(label, exc)
        else:
            self.pass_(label)


def assert_equal(actual, expected, label="value"):
    if actual != expected:
        raise RegressionFailure(
            f"{label}: expected={expected!r}, actual={actual!r}"
        )


def assert_true(value, label="condition"):
    if not value:
        raise RegressionFailure(
            f"{label}: expected truthy, actual={value!r}"
        )


def load_local_module(module_name):
    root = Path(__file__).resolve().parent
    path = root / f"{module_name}.py"

    if not path.is_file():
        raise RegressionFailure(
            f"missing module: {path.name}"
        )

    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )
    module = importlib.util.module_from_spec(
        spec
    )
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def dataframe_for_signal(column, values):
    values = list(values)
    return pd.DataFrame({
        "distance":
            np.arange(
                len(values),
                dtype=float,
            ),
        column:
            np.asarray(
                values,
                dtype=float,
            ),
    })


def make_two_lap_dataframe(
    reference_trace,
    comparison_trace,
):
    n = max(
        len(reference_trace),
        len(comparison_trace),
    )

    reference = np.pad(
        np.asarray(
            reference_trace,
            dtype=float,
        ),
        (
            0,
            n - len(reference_trace),
        ),
        constant_values=0.0,
    )
    comparison = np.pad(
        np.asarray(
            comparison_trace,
            dtype=float,
        ),
        (
            0,
            n - len(comparison_trace),
        ),
        constant_values=0.0,
    )

    return pd.DataFrame({
        "distance":
            np.arange(
                n,
                dtype=float,
            ),
        "throttle_a":
            reference,
        "throttle_b":
            comparison,
    })


def core_event(event):
    keys = (
        "onset_distance_m",
        "confirmation_distance_m",
        "release_distance_m",
        "release_confirmed",
        "length_m",
        "peak_throttle_percent",
        "peak_distance_m",
        "confirmed",
    )
    return {
        key: event.get(key)
        for key in keys
    }


def section(title):
    print()
    print(title)
    print("-" * len(title))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Race Engineer deterministic Python regression suite."
        )
    )
    parser.add_argument(
        "--analyzer",
        default=None,
        help=(
            "Optional path to analyze_telemetry.py. "
            "If omitted, auto-detects ./analyze_telemetry.py."
        ),
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    runner = Runner()

    brake = load_local_module(
        "braking_point_v2_1"
    )
    throttle_11 = load_local_module(
        "throttle_point_v1_1"
    )
    throttle = load_local_module(
        "throttle_point_v1_2_1"
    )
    sequence = load_local_module(
        "throttle_episode_sequence_v1_0"
    )
    sustained = load_local_module(
        "throttle_sustained_modulation_v1_0"
    )
    recovery = load_local_module(
        "apply_objective_python_recovery_2026_08_13"
    )

    print(
        f"RACE ENGINEER PYTHON REGRESSION SUITE v{SUITE_VERSION}"
    )

    # ========================================================
    # VERSION / CONTRACT
    # ========================================================
    section("VERSION CONTRACT")

    runner.run(
        "Brake detector = 2.1 / schema 2.1",
        lambda: (
            assert_equal(
                brake.BRAKING_POINT_VERSION,
                "2.1",
                "BRAKING_POINT_VERSION",
            ),
            assert_equal(
                brake.BRAKING_POINT_SCHEMA_VERSION,
                "2.1",
                "BRAKING_POINT_SCHEMA_VERSION",
            ),
        ),
    )

    runner.run(
        "Throttle detector = 1.2.1 / schema 1.2",
        lambda: (
            assert_equal(
                throttle.THROTTLE_POINT_VERSION,
                "1.2.1",
                "THROTTLE_POINT_VERSION",
            ),
            assert_equal(
                throttle.THROTTLE_POINT_SCHEMA_VERSION,
                "1.2",
                "THROTTLE_POINT_SCHEMA_VERSION",
            ),
        ),
    )

    runner.run(
        "Throttle sequence = 1.0 / observational",
        lambda: (
            assert_equal(
                sequence.THROTTLE_EPISODE_SEQUENCE_VERSION,
                "1.0",
                "THROTTLE_EPISODE_SEQUENCE_VERSION",
            ),
            assert_true(
                sequence
                .throttle_episode_sequence_config_summary()
                ["observational_only"],
                "observational_only",
            ),
            assert_equal(
                sequence
                .throttle_episode_sequence_config_summary()
                ["affects_ranking"],
                False,
                "affects_ranking",
            ),
            assert_equal(
                sequence
                .throttle_episode_sequence_config_summary()
                ["authorizes_coaching"],
                False,
                "authorizes_coaching",
            ),
        ),
    )

    runner.run(
        "Throttle sustained modulation = 1.0 / observational",
        lambda: (
            assert_equal(
                sustained.THROTTLE_SUSTAINED_MODULATION_VERSION,
                "1.0",
                "THROTTLE_SUSTAINED_MODULATION_VERSION",
            ),
            assert_equal(
                sustained.THROTTLE_SUSTAINED_MODULATION_SCHEMA_VERSION,
                "1.0",
                "THROTTLE_SUSTAINED_MODULATION_SCHEMA_VERSION",
            ),
            assert_equal(
                sustained.sustained_modulation_config_summary()[
                    "observational_only"
                ],
                True,
                "observational_only",
            ),
            assert_equal(
                sustained.sustained_modulation_config_summary()[
                    "affects_ranking"
                ],
                False,
                "affects_ranking",
            ),
            assert_equal(
                sustained.sustained_modulation_config_summary()[
                    "authorizes_coaching"
                ],
                False,
                "authorizes_coaching",
            ),
        ),
    )

    # ========================================================
    # BRAKE 2.1
    # ========================================================
    section("BRAKE 2.1")

    def brake_basic():
        trace = (
            [0] * 10
            + [6, 16, 40, 80, 90, 70, 30, 5]
            + [1, 1, 1, 1]
            + [0] * 5
        )
        df = dataframe_for_signal(
            "brake_a",
            trace,
        )
        events = brake.detect_braking_events(
            df,
            "brake_a",
        )
        assert_equal(
            len(events),
            1,
            "event_count",
        )
        event = events[0]
        assert_equal(
            event["onset_distance_m"],
            10.0,
            "onset",
        )
        assert_equal(
            event["confirmation_distance_m"],
            11.0,
            "confirmation",
        )
        assert_equal(
            event["release_distance_m"],
            18.0,
            "release",
        )
        assert_equal(
            event["release_confirmed"],
            True,
            "release_confirmed",
        )

    runner.run(
        "physical onset/release detection",
        brake_basic,
    )

    def brake_end_trace():
        trace = (
            [0] * 10
            + [6, 20, 55, 80, 75, 65, 50, 40, 30, 25]
        )
        df = dataframe_for_signal(
            "brake_a",
            trace,
        )
        events = brake.detect_braking_events(
            df,
            "brake_a",
        )
        assert_equal(
            len(events),
            1,
            "event_count",
        )
        assert_equal(
            events[0]["onset_distance_m"],
            10.0,
            "onset",
        )
        assert_equal(
            events[0]["release_confirmed"],
            False,
            "release_confirmed",
        )

    runner.run(
        "active trace end preserves onset",
        brake_end_trace,
    )

    # ========================================================
    # THROTTLE 1.2.1
    # ========================================================
    section("THROTTLE 1.2.1")

    def throttle_v11_invariance():
        trace = (
            [0] * 10
            + [6, 22, 45, 80, 96]
            + [98] * 20
            + [50, 20, 5, 1]
            + [0] * 10
        )
        df = dataframe_for_signal(
            "throttle_a",
            trace,
        )

        old_events = (
            throttle_11.detect_throttle_events(
                df,
                "throttle_a",
            )
        )
        new_events = (
            throttle.detect_throttle_events(
                df,
                "throttle_a",
            )
        )

        assert_equal(
            len(old_events),
            len(new_events),
            "event_count",
        )

        for old, new in zip(
            old_events,
            new_events,
        ):
            assert_equal(
                core_event(new),
                core_event(old),
                "v1.1 core event",
            )

    runner.run(
        "onset/release v1.1 invariance",
        throttle_v11_invariance,
    )

    def full_throttle_confirmed():
        trace = (
            [0] * 10
            + [6, 22, 45, 80, 96]
            + [98] * 20
            + [1]
            + [0] * 10
        )
        df = dataframe_for_signal(
            "throttle_a",
            trace,
        )
        event = (
            throttle.detect_throttle_events(
                df,
                "throttle_a",
            )[0]
        )
        assert_equal(
            event[
                "full_throttle_attainment_confirmed"
            ],
            True,
            "full_throttle_confirmed",
        )

    runner.run(
        "full-throttle sustained confirmation",
        full_throttle_confirmed,
    )

    def full_throttle_transient_rejected():
        trace = (
            [0] * 10
            + [6, 22, 45, 80, 96, 75]
            + [80] * 20
            + [1]
            + [0] * 10
        )
        df = dataframe_for_signal(
            "throttle_a",
            trace,
        )
        event = (
            throttle.detect_throttle_events(
                df,
                "throttle_a",
            )[0]
        )
        assert_equal(
            event[
                "full_throttle_attainment_confirmed"
            ],
            False,
            "transient full-throttle",
        )

    runner.run(
        "full-throttle transient rejected",
        full_throttle_transient_rejected,
    )

    def partial_lift_short():
        trace = [
            94, 94, 93, 90,
            70, 67, 68, 70,
            73, 77, 82, 85,
            87, 94, 94,
        ]
        distance = np.arange(
            len(trace),
            dtype=float,
        )
        result = throttle._detect_partial_lifts(
            distance,
            np.asarray(
                trace,
                dtype=float,
            ),
            0,
            len(trace) - 1,
        )
        assert_equal(
            len(result),
            1,
            "partial_lift_count",
        )
        assert_equal(
            result[0]["length_m"],
            8.0,
            "partial_lift_length",
        )

    runner.run(
        "short recovered partial lift accepted",
        partial_lift_short,
    )

    def partial_lift_medium():
        trace = [
            85, 85, 85, 85,
            65, 58, 54, 55,
            58, 62, 66, 70,
            74, 78, 82, 85,
            85, 85,
        ]
        distance = np.arange(
            len(trace),
            dtype=float,
        )
        result = throttle._detect_partial_lifts(
            distance,
            np.asarray(
                trace,
                dtype=float,
            ),
            0,
            len(trace) - 1,
        )
        assert_equal(
            len(result),
            1,
            "partial_lift_count",
        )

    runner.run(
        "medium recovered partial lift accepted",
        partial_lift_medium,
    )

    def partial_lift_deep_long_rejected():
        trace = (
            [80, 80, 80, 80]
            + [
                60, 40, 25,
                20.5, 20.2, 20.1,
                19.9,
            ]
            + [20] * 70
            + [30, 45, 60, 75, 80]
        )
        distance = np.arange(
            len(trace),
            dtype=float,
        )
        result = throttle._detect_partial_lifts(
            distance,
            np.asarray(
                trace,
                dtype=float,
            ),
            0,
            len(trace) - 1,
        )
        assert_equal(
            len(result),
            0,
            "partial_lift_count",
        )

    runner.run(
        "deep/long modulation rejected as partial lift",
        partial_lift_deep_long_rejected,
    )

    def monotonic_pairing_skip():
        refs = [
            {
                "throttle_event_id": "a1",
                "onset_distance_m": 100,
                "release_distance_m": 150,
                "release_confirmed": True,
            },
            {
                "throttle_event_id": "a2",
                "onset_distance_m": 300,
                "release_distance_m": 350,
                "release_confirmed": True,
            },
            {
                "throttle_event_id": "a3",
                "onset_distance_m": 500,
                "release_distance_m": 550,
                "release_confirmed": True,
            },
        ]
        cmps = [
            {
                "throttle_event_id": "b1",
                "onset_distance_m": 105,
                "release_distance_m": 152,
                "release_confirmed": True,
            },
            {
                "throttle_event_id": "bX",
                "onset_distance_m": 210,
                "release_distance_m": 240,
                "release_confirmed": True,
            },
            {
                "throttle_event_id": "b2",
                "onset_distance_m": 310,
                "release_distance_m": 360,
                "release_confirmed": True,
            },
            {
                "throttle_event_id": "b3",
                "onset_distance_m": 495,
                "release_distance_m": 548,
                "release_confirmed": True,
            },
        ]

        pairs = throttle.pair_throttle_events(
            refs,
            cmps,
        )

        ids = [
            (
                pair["reference_event_id"],
                pair["comparison_event_id"],
            )
            for pair in pairs
        ]

        assert_equal(
            ids,
            [
                ("a1", "b1"),
                ("a2", "b2"),
                ("a3", "b3"),
            ],
            "monotonic pairs",
        )

    runner.run(
        "monotonic pairing skips unmatched event",
        monotonic_pairing_skip,
    )

    # ========================================================
    # MULTI-EVENT THROTTLE SEQUENCE 1.0
    # ========================================================
    section("THROTTLE EPISODE SEQUENCE 1.0")

    def two_event_trace(
        first_onset,
        second_onset,
        length=180,
    ):
        trace = [0.0] * length

        def add_event(onset, hold=22):
            values = (
                [6, 24, 55, 82, 96]
                + [98] * hold
                + [50, 18, 5, 1]
                + [0] * 10
            )
            for offset, value in enumerate(
                values
            ):
                index = onset + offset
                if index < len(trace):
                    trace[index] = value

        add_event(first_onset)
        add_event(second_onset)
        return trace

    def multi_event_sequence():
        ref = two_event_trace(
            20,
            95,
        )
        cmp_ = two_event_trace(
            22,
            100,
        )

        df = make_two_lap_dataframe(
            ref,
            cmp_,
        )

        reference_events = (
            throttle.detect_throttle_events(
                df,
                "throttle_a",
            )
        )
        comparison_events = (
            throttle.detect_throttle_events(
                df,
                "throttle_b",
            )
        )
        pairs = throttle.pair_throttle_events(
            reference_events,
            comparison_events,
        )

        episode = {
            "zone_id": 1,
            "start_distance_m": 15.0,
            "end_distance_m": 145.0,
            "action_channels": [
                "throttle",
            ],
        }

        result = (
            sequence
            .build_throttle_event_sequence_for_episode(
                episode,
                reference_events,
                comparison_events,
                pairs,
            )
        )

        assert_equal(
            result["status"],
            "VALID",
            "status",
        )
        assert_equal(
            result["reference_event_count"],
            2,
            "reference_event_count",
        )
        assert_equal(
            result["comparison_event_count"],
            2,
            "comparison_event_count",
        )
        assert_equal(
            result["paired_event_count"],
            2,
            "paired_event_count",
        )
        assert_equal(
            result[
                "multiple_physical_events_in_episode"
            ],
            True,
            "multiple_events",
        )
        assert_equal(
            [
                item["pair_status"]
                for item in result[
                    "sequence_items"
                ]
            ],
            [
                "PAIRED_IN_EPISODE",
                "PAIRED_IN_EPISODE",
            ],
            "pair statuses",
        )
        assert_equal(
            result["authorized_coaching"],
            False,
            "authorized_coaching",
        )
        assert_equal(
            result["affects_ranking"],
            False,
            "affects_ranking",
        )

    runner.run(
        "two physical throttle events preserved in one episode",
        multi_event_sequence,
    )

    def sequence_single_event_scope():
        ref = two_event_trace(
            20,
            95,
        )
        cmp_ = two_event_trace(
            22,
            100,
        )

        df = make_two_lap_dataframe(
            ref,
            cmp_,
        )

        reference_events = (
            throttle.detect_throttle_events(
                df,
                "throttle_a",
            )
        )
        comparison_events = (
            throttle.detect_throttle_events(
                df,
                "throttle_b",
            )
        )
        pairs = throttle.pair_throttle_events(
            reference_events,
            comparison_events,
        )

        episode = {
            "zone_id": 1,
            "start_distance_m": 15.0,
            "end_distance_m": 60.0,
            "action_channels": [
                "throttle",
            ],
        }

        result = (
            sequence
            .build_throttle_event_sequence_for_episode(
                episode,
                reference_events,
                comparison_events,
                pairs,
            )
        )

        assert_equal(
            result[
                "multiple_physical_events_in_episode"
            ],
            False,
            "multiple_events",
        )
        assert_equal(
            result["paired_event_count"],
            1,
            "paired_event_count",
        )

    runner.run(
        "episode scope does not pull unrelated second event",
        sequence_single_event_scope,
    )

    def no_throttle_channel():
        result = (
            sequence
            .build_throttle_event_sequence_for_episode(
                {
                    "start_distance_m": 0,
                    "end_distance_m": 100,
                    "action_channels": [
                        "brake",
                    ],
                },
                [],
                [],
                [],
            )
        )
        assert_equal(
            result,
            None,
            "result",
        )

    runner.run(
        "non-throttle episode ignored",
        no_throttle_channel,
    )

    def enrichment_does_not_change_ranking():
        ref = two_event_trace(
            20,
            95,
        )
        cmp_ = two_event_trace(
            22,
            100,
        )
        df = make_two_lap_dataframe(
            ref,
            cmp_,
        )

        throttle_episode = {
            "episode_id": 10,
            "zone_id": 1,
            "start_distance_m": 15.0,
            "end_distance_m": 145.0,
            "action_channels": [
                "throttle",
            ],
        }
        brake_episode = {
            "episode_id": 11,
            "zone_id": 2,
            "start_distance_m": 150.0,
            "end_distance_m": 170.0,
            "action_channels": [
                "brake",
            ],
        }

        objective = {
            "driver_action_episode_ranking": [
                dict(throttle_episode),
                dict(brake_episode),
            ],
            "loss_ranking": [
                {
                    "driver_action_episodes": [
                        dict(throttle_episode),
                        dict(brake_episode),
                    ]
                }
            ],
        }

        before_ids = [
            item["episode_id"]
            for item in objective[
                "driver_action_episode_ranking"
            ]
        ]

        sequence.enrich_objective_with_throttle_event_sequences(
            df,
            objective,
        )

        after_ids = [
            item["episode_id"]
            for item in objective[
                "driver_action_episode_ranking"
            ]
        ]

        assert_equal(
            after_ids,
            before_ids,
            "ranking order",
        )
        assert_true(
            "throttle_event_sequence"
            in objective[
                "driver_action_episode_ranking"
            ][0],
            "throttle sequence attached",
        )
        assert_equal(
            "throttle_event_sequence"
            in objective[
                "driver_action_episode_ranking"
            ][1],
            False,
            "brake-only episode untouched",
        )
        metadata = objective[
            "throttle_episode_sequence_detection"
        ]
        assert_equal(
            metadata["version"],
            "1.0",
            "sequence metadata version",
        )
        assert_equal(
            metadata["config"]["affects_ranking"],
            False,
            "metadata affects_ranking",
        )

    runner.run(
        "sequence enrichment preserves ranking/order",
        enrichment_does_not_change_ranking,
    )

    # ========================================================
    # THROTTLE SUSTAINED MODULATION 1.0
    # ========================================================
    section("THROTTLE SUSTAINED MODULATION 1.0")

    def _single_event_trace(body, prefix=10, suffix=16):
        return (
            [0.0] * prefix
            + [6.0, 24.0, 55.0, 80.0, 96.0]
            + list(body)
            + [70.0, 45.0, 20.0, 5.0, 1.0]
            + [0.0] * suffix
        )

    def sustained_deep_long_detected():
        body = (
            [98.0] * 8
            + [80.0, 60.0, 40.0, 25.0, 12.0]
            + [10.0] * 65
            + [20.0, 35.0, 50.0, 65.0, 80.0, 92.0, 98.0]
            + [98.0] * 8
        )
        trace = _single_event_trace(body)
        df = make_two_lap_dataframe(trace, trace)
        events = throttle.detect_throttle_events(df, "throttle_a")
        assert_equal(len(events), 1, "event_count")
        mods = sustained.detect_sustained_modulations_in_event(
            df,
            "throttle_a",
            events[0],
        )
        assert_equal(len(mods), 1, "modulation_count")
        assert_equal(mods[0]["classification"], "deep_and_long", "classification")
        assert_true(mods[0]["length_m"] > 60.0, "length > partial-lift max")
        assert_true(mods[0]["minimum_throttle_percent"] < 20.0, "minimum < partial-lift floor")

    runner.run(
        "deep/long recovered modulation detected",
        sustained_deep_long_detected,
    )

    def sustained_does_not_duplicate_partial_lift():
        body = (
            [98.0] * 6
            + [78.0, 68.0, 60.0]
            + [60.0] * 18
            + [65.0, 72.0, 80.0, 88.0, 94.0, 98.0]
            + [98.0] * 8
        )
        trace = _single_event_trace(body)
        df = make_two_lap_dataframe(trace, trace)
        events = throttle.detect_throttle_events(df, "throttle_a")
        assert_equal(len(events), 1, "event_count")
        partial = events[0].get("partial_lifts", [])
        assert_true(len(partial) >= 1, "partial lift detected")
        mods = sustained.detect_sustained_modulations_in_event(
            df,
            "throttle_a",
            events[0],
        )
        assert_equal(len(mods), 0, "sustained modulation count")

    runner.run(
        "partial-lift envelope is not duplicated",
        sustained_does_not_duplicate_partial_lift,
    )

    def sustained_release_rejected():
        body = (
            [98.0] * 8
            + [80.0, 60.0, 35.0, 15.0]
            + [10.0] * 35
            + [5.0, 1.0]
            + [0.0] * 12
            + [20.0, 50.0, 80.0, 98.0]
        )
        trace = _single_event_trace(body, suffix=8)
        df = make_two_lap_dataframe(trace, trace)
        events = throttle.detect_throttle_events(df, "throttle_a")
        assert_true(len(events) >= 1, "event_count")
        all_mods = []
        for event in events:
            all_mods.extend(
                sustained.detect_sustained_modulations_in_event(
                    df,
                    "throttle_a",
                    event,
                )
            )
        assert_equal(len(all_mods), 0, "release must not become modulation")

    runner.run(
        "confirmed release is not sustained modulation",
        sustained_release_rejected,
    )

    def sustained_enrichment_preserves_ranking():
        reference = _single_event_trace(
            [98.0] * 100
        )
        comparison = _single_event_trace(
            [98.0] * 8
            + [80.0, 60.0, 40.0, 25.0, 12.0]
            + [10.0] * 65
            + [20.0, 35.0, 50.0, 65.0, 80.0, 92.0, 98.0]
            + [98.0] * 15
        )
        df = make_two_lap_dataframe(reference, comparison)
        throttle_episode = {
            "episode_id": 20,
            "zone_id": 1,
            "start_distance_m": 10.0,
            "end_distance_m": 120.0,
            "action_channels": ["throttle"],
        }
        brake_episode = {
            "episode_id": 21,
            "zone_id": 2,
            "start_distance_m": 130.0,
            "end_distance_m": 150.0,
            "action_channels": ["brake"],
        }
        objective = {
            "driver_action_episode_ranking": [
                dict(throttle_episode),
                dict(brake_episode),
            ],
            "loss_ranking": [
                {
                    "driver_action_episodes": [
                        dict(throttle_episode),
                        dict(brake_episode),
                    ]
                }
            ],
        }
        before_ids = [
            item["episode_id"]
            for item in objective["driver_action_episode_ranking"]
        ]
        sustained.enrich_objective_with_sustained_throttle_modulations(
            df,
            objective,
        )
        after_ids = [
            item["episode_id"]
            for item in objective["driver_action_episode_ranking"]
        ]
        assert_equal(after_ids, before_ids, "ranking order")
        assert_equal(
            objective["throttle_sustained_modulation_detection"]["version"],
            "1.0",
            "metadata version",
        )
        assert_equal(
            objective["throttle_sustained_modulation_detection"]["config"]["affects_ranking"],
            False,
            "metadata affects_ranking",
        )
        assert_equal(
            "throttle_sustained_modulation_comparison"
            in objective["driver_action_episode_ranking"][1],
            False,
            "brake-only episode untouched",
        )

    runner.run(
        "sustained modulation enrichment preserves ranking/order",
        sustained_enrichment_preserves_ranking,
    )

    # ========================================================
    # RECOVERY PATCHER
    # ========================================================
    section("RECOVERY PATCHER")

    def recovery_from_unpatched_source():
        sample = """import json
from sector_analysis import SectorAnalysis

def demo(zones, real_delta, comparison):
            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
            return objective_analysis
"""
        patched = recovery.patch_text(
            sample
        )
        errors = recovery.verify_text(
            patched
        )
        assert_equal(
            errors,
            [],
            "recovery verification",
        )

    runner.run(
        "unpatched analyzer -> canonical objective hooks",
        recovery_from_unpatched_source,
    )

    def recovery_migrates_old_imports():
        sample = """import json
from sector_analysis import SectorAnalysis
from braking_point_v2_0 import enrich_objective_with_braking_points
from throttle_point_v1_1 import enrich_objective_with_throttle_points

def demo(zones, real_delta, comparison):
            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
            enrich_objective_with_braking_points(
                comparison,
                objective_analysis,
            )
            enrich_objective_with_throttle_points(
                comparison,
                objective_analysis,
            )
            return objective_analysis
"""
        patched = recovery.patch_text(
            sample
        )
        errors = recovery.verify_text(
            patched
        )
        assert_equal(
            errors,
            [],
            "recovery verification",
        )
        assert_equal(
            "braking_point_v2_0"
            in patched,
            False,
            "legacy brake import",
        )
        assert_equal(
            "throttle_point_v1_1"
            in patched,
            False,
            "legacy throttle import",
        )

    runner.run(
        "legacy imports/hooks migrate without duplication",
        recovery_migrates_old_imports,
    )

    def recovery_idempotent():
        sample = """import json
from sector_analysis import SectorAnalysis

def demo(zones, real_delta, comparison):
            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
            return objective_analysis
"""
        once = recovery.patch_text(
            sample
        )
        twice = recovery.patch_text(
            once
        )
        assert_equal(
            twice,
            once,
            "second patch result",
        )

    runner.run(
        "recovery patch is text-idempotent",
        recovery_idempotent,
    )

    # ========================================================
    # OPTIONAL REAL ANALYZER INSTALLATION AUDIT
    # ========================================================
    section("ANALYZER INSTALLATION")

    if args.analyzer:
        analyzer_path = Path(
            args.analyzer
        )
    else:
        analyzer_path = (
            root / "analyze_telemetry.py"
        )

    if analyzer_path.is_file():
        def analyzer_installation():
            text = analyzer_path.read_text(
                encoding="utf-8"
            )
            errors = recovery.verify_text(
                text
            )
            assert_equal(
                errors,
                [],
                "analyzer objective hooks",
            )

        runner.run(
            f"{analyzer_path.name} objective hooks",
            analyzer_installation,
        )
    else:
        runner.skip(
            "analyze_telemetry.py objective hooks",
            (
                "file not found; pass "
                "--analyzer PATH to audit another copy"
            ),
        )

    # ========================================================
    # SUMMARY
    # ========================================================
    print()
    print("=" * 60)
    print(
        "RESULT: "
        f"{runner.passed} PASS / "
        f"{runner.failed} FAIL / "
        f"{runner.skipped} SKIP"
    )
    print("=" * 60)

    if runner.failed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
