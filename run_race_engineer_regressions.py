from pathlib import Path
import argparse
import importlib.util
import sys
import tempfile

import numpy as np
import pandas as pd


SUITE_VERSION = "1.3"


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
    recurrence = load_local_module(
        "full_throttle_recurrence_v1_0"
    )
    modulation_recurrence = load_local_module(
        "throttle_modulation_recurrence_v1_0"
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

    runner.run(
        "Full-throttle recurrence = 1.0 / session observational",
        lambda: (
            assert_equal(
                recurrence.FULL_THROTTLE_RECURRENCE_VERSION,
                "1.0",
                "FULL_THROTTLE_RECURRENCE_VERSION",
            ),
            assert_equal(
                recurrence.FULL_THROTTLE_RECURRENCE_SCHEMA_VERSION,
                "1.0",
                "FULL_THROTTLE_RECURRENCE_SCHEMA_VERSION",
            ),
            assert_equal(
                recurrence.full_throttle_recurrence_config_summary()[
                    "observational_only"
                ],
                True,
                "observational_only",
            ),
            assert_equal(
                recurrence.full_throttle_recurrence_config_summary()[
                    "affects_session_priority"
                ],
                False,
                "affects_session_priority",
            ),
            assert_equal(
                recurrence.full_throttle_recurrence_config_summary()[
                    "authorizes_coaching"
                ],
                False,
                "authorizes_coaching",
            ),
        ),
    )

    runner.run(
        "Throttle modulation recurrence = 1.0 / session observational",
        lambda: (
            assert_equal(
                modulation_recurrence.THROTTLE_MODULATION_RECURRENCE_VERSION,
                "1.0",
                "THROTTLE_MODULATION_RECURRENCE_VERSION",
            ),
            assert_equal(
                modulation_recurrence.THROTTLE_MODULATION_RECURRENCE_SCHEMA_VERSION,
                "1.0",
                "THROTTLE_MODULATION_RECURRENCE_SCHEMA_VERSION",
            ),
            assert_equal(
                modulation_recurrence
                .throttle_modulation_recurrence_config_summary()[
                    "observational_only"
                ],
                True,
                "observational_only",
            ),
            assert_equal(
                modulation_recurrence
                .throttle_modulation_recurrence_config_summary()[
                    "affects_session_priority"
                ],
                False,
                "affects_session_priority",
            ),
            assert_equal(
                modulation_recurrence
                .throttle_modulation_recurrence_config_summary()[
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
    # FULL-THROTTLE ATTAINMENT RECURRENCE 1.0
    # ========================================================
    section("FULL-THROTTLE ATTAINMENT RECURRENCE 1.0")

    def _ft_result(
        reference_event_id,
        direction,
        delta_m=None,
        status="VALID",
        reference_attained=True,
        comparison_attained=True,
        reference_attainment_m=1000.0,
        comparison_attainment_m=None,
        reason=None,
    ):
        if comparison_attainment_m is None and delta_m is not None:
            comparison_attainment_m = reference_attainment_m + delta_m

        return {
            "status": status,
            "throttle_pair_id": (
                f"{reference_event_id}|cmp"
                if reference_event_id
                else None
            ),
            "reference_event_id": reference_event_id,
            "comparison_event_id": "cmp",
            "reference_attainment_confirmed": reference_attained,
            "comparison_attainment_confirmed": comparison_attained,
            "reference_attainment_m": (
                reference_attainment_m
                if reference_attained
                else None
            ),
            "comparison_attainment_m": (
                comparison_attainment_m
                if comparison_attained
                else None
            ),
            "reference_onset_to_full_throttle_m": (
                80.0 if reference_attained else None
            ),
            "comparison_onset_to_full_throttle_m": (
                80.0 + delta_m
                if comparison_attained and delta_m is not None
                else None
            ),
            "comparison_minus_reference_m": delta_m,
            "relative_direction": direction,
            "authorized_numeric_coaching": False,
            "observational_only": True,
            "reason": reason,
        }

    def _ft_comparison(
        comparison_lap,
        results,
        reference_lap=4,
    ):
        episodes = []
        for index, result in enumerate(results, start=1):
            episodes.append({
                "episode_id": index,
                "global_rank": index,
                "zone_id": index,
                "start_distance_m": 900.0 + index * 10.0,
                "end_distance_m": 950.0 + index * 10.0,
                "action_time_loss_s": 0.1 / index,
                "action_channels": ["throttle"],
                "throttle_full_throttle_attainment_comparison": result,
            })
        return {
            "reference_lap": reference_lap,
            "comparison_lap": comparison_lap,
            "objective_analysis": {
                "driver_action_episode_ranking": episodes,
            },
        }

    def recurrence_repeated_timing():
        analysis = {
            "comparisons": [
                _ft_comparison(
                    3,
                    [
                        _ft_result(
                            "throttle_a:08",
                            "earlier_in_comparison_lap",
                            -24.0,
                            reference_attainment_m=3243.0,
                        )
                    ],
                ),
                _ft_comparison(
                    2,
                    [
                        _ft_result(
                            "throttle_a:08",
                            "earlier_in_comparison_lap",
                            -10.0,
                            reference_attainment_m=3243.0,
                        )
                    ],
                ),
                _ft_comparison(1, []),
            ]
        }

        recurrence.enrich_analysis_with_full_throttle_attainment_recurrence(
            analysis
        )
        result = analysis["full_throttle_attainment_recurrence"]
        assert_equal(result["repeated_pattern_count"], 1, "repeated count")
        pattern = result["patterns"][0]
        assert_equal(
            pattern["selected_direction"],
            "earlier_in_comparison_lap",
            "selected direction",
        )
        assert_equal(
            pattern["recurrence_status"],
            "REPEATED_CONSISTENT",
            "recurrence status",
        )
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(
            pattern["comparison_minus_reference_m_median"],
            -17.0,
            "median delta",
        )
        assert_equal(pattern["missing_comparison_count"], 1, "missing comparisons")
        assert_equal(pattern["authorized_coaching"], False, "coaching")

    runner.run(
        "repeated timing direction across comparisons",
        recurrence_repeated_timing,
    )

    def recurrence_repeated_attainment_state():
        analysis = {
            "comparisons": [
                _ft_comparison(
                    3,
                    [
                        _ft_result(
                            "throttle_a:04",
                            "comparison_attained_reference_not_confirmed",
                            None,
                            reference_attained=False,
                            comparison_attained=True,
                            reference_attainment_m=None,
                            comparison_attainment_m=2605.0,
                        )
                    ],
                ),
                _ft_comparison(
                    2,
                    [
                        _ft_result(
                            "throttle_a:04",
                            None,
                            None,
                            status="UNAVAILABLE",
                            reference_attained=False,
                            comparison_attained=False,
                            reference_attainment_m=None,
                            comparison_attainment_m=None,
                            reason="full_throttle_not_confirmed_in_either_event",
                        )
                    ],
                ),
                _ft_comparison(
                    1,
                    [
                        _ft_result(
                            "throttle_a:04",
                            "comparison_attained_reference_not_confirmed",
                            None,
                            reference_attained=False,
                            comparison_attained=True,
                            reference_attainment_m=None,
                            comparison_attainment_m=2588.0,
                        )
                    ],
                ),
            ]
        }

        result = recurrence.build_full_throttle_attainment_recurrence(
            analysis["comparisons"]
        )
        pattern = result["patterns"][0]
        assert_equal(pattern["is_repeated"], True, "is_repeated")
        assert_equal(pattern["pattern_kind"], "attainment_state", "pattern kind")
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(
            pattern["unavailable_observation_count"],
            1,
            "unavailable count",
        )
        assert_equal(
            pattern["recurrence_status"],
            "REPEATED_CONSISTENT",
            "recurrence status",
        )

    runner.run(
        "repeated attained/not-attained state ignores unavailable evidence",
        recurrence_repeated_attainment_state,
    )

    def recurrence_mixed_not_repeated():
        comparisons = [
            _ft_comparison(
                3,
                [
                    _ft_result(
                        "throttle_a:07",
                        "earlier_in_comparison_lap",
                        -11.0,
                    )
                ],
            ),
            _ft_comparison(
                1,
                [
                    _ft_result(
                        "throttle_a:07",
                        "later_in_comparison_lap",
                        42.0,
                    )
                ],
            ),
        ]

        result = recurrence.build_full_throttle_attainment_recurrence(comparisons)
        pattern = result["patterns"][0]
        assert_equal(pattern["is_repeated"], False, "is_repeated")
        assert_equal(pattern["recurrence_status"], "NOT_REPEATED", "status")
        assert_equal(
            pattern["direction_counts"],
            {
                "earlier_in_comparison_lap": 1,
                "later_in_comparison_lap": 1,
            },
            "direction counts",
        )

    runner.run(
        "mixed earlier/later evidence is not promoted to recurrence",
        recurrence_mixed_not_repeated,
    )

    def recurrence_duplicate_episode_dedup():
        repeated = _ft_result(
            "throttle_a:09",
            "later_in_comparison_lap",
            26.0,
            reference_attainment_m=3737.0,
        )
        comparison3 = _ft_comparison(3, [dict(repeated), dict(repeated)])
        comparison2 = _ft_comparison(
            2,
            [
                _ft_result(
                    "throttle_a:09",
                    "later_in_comparison_lap",
                    44.0,
                    reference_attainment_m=3737.0,
                )
            ],
        )

        result = recurrence.build_full_throttle_attainment_recurrence(
            [comparison3, comparison2]
        )
        pattern = result["patterns"][0]
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(pattern["valid_observation_count"], 2, "valid observations")
        duplicate_counts = [
            item["duplicate_episode_count"]
            for item in pattern["observations"]
        ]
        assert_true(max(duplicate_counts) == 1, "duplicate episode recorded")

    runner.run(
        "duplicate episode assignment cannot inflate recurrence",
        recurrence_duplicate_episode_dedup,
    )

    def recurrence_enrichment_preserves_session():
        comparisons = [
            _ft_comparison(
                3,
                [
                    _ft_result(
                        "throttle_a:08",
                        "earlier_in_comparison_lap",
                        -24.0,
                    )
                ],
            ),
            _ft_comparison(
                2,
                [
                    _ft_result(
                        "throttle_a:08",
                        "earlier_in_comparison_lap",
                        -10.0,
                    )
                ],
            ),
        ]

        analysis = {
            "metadata": {"sentinel": "keep"},
            "comparisons": comparisons,
        }

        before_laps = [
            comp["comparison_lap"]
            for comp in analysis["comparisons"]
        ]
        before_episode_ids = [
            [
                episode["episode_id"]
                for episode in comp["objective_analysis"][
                    "driver_action_episode_ranking"
                ]
            ]
            for comp in analysis["comparisons"]
        ]

        recurrence.enrich_analysis_with_full_throttle_attainment_recurrence(
            analysis
        )

        after_laps = [
            comp["comparison_lap"]
            for comp in analysis["comparisons"]
        ]
        after_episode_ids = [
            [
                episode["episode_id"]
                for episode in comp["objective_analysis"][
                    "driver_action_episode_ranking"
                ]
            ]
            for comp in analysis["comparisons"]
        ]

        assert_equal(after_laps, before_laps, "comparison order")
        assert_equal(after_episode_ids, before_episode_ids, "episode ranking")
        assert_equal(analysis["metadata"]["sentinel"], "keep", "metadata sentinel")
        config = analysis["full_throttle_attainment_recurrence"]["config"]
        assert_equal(config["affects_ranking"], False, "affects ranking")
        assert_equal(
            config["affects_session_priority"],
            False,
            "affects session priority",
        )

    runner.run(
        "session recurrence enrichment preserves comparisons/ranking",
        recurrence_enrichment_preserves_session,
    )

    # ========================================================
    # THROTTLE MODULATION RECURRENCE 1.0
    # ========================================================
    section("THROTTLE MODULATION RECURRENCE 1.0")

    def _partial_result(
        reference_event_id,
        reference_count,
        comparison_count,
        status="VALID",
    ):
        return {
            "status": status,
            "throttle_pair_id": f"{reference_event_id}|cmp",
            "reference_event_id": reference_event_id,
            "comparison_event_id": "cmp",
            "reference_partial_lift_count": reference_count,
            "comparison_partial_lift_count": comparison_count,
            "count_difference": comparison_count - reference_count,
            "comparison_has_additional_partial_lift": (
                comparison_count > reference_count
            ),
            "comparison_has_fewer_partial_lifts": (
                comparison_count < reference_count
            ),
            "reference_partial_lifts": [],
            "comparison_partial_lifts": [],
            "authorized_numeric_coaching": False,
            "observational_only": True,
        }

    def _mod_comparison(
        comparison_lap,
        partial_results=None,
        sustained_results=None,
        reference_lap=4,
    ):
        partial_results = partial_results or []
        sustained_results = sustained_results or []
        count = max(len(partial_results), len(sustained_results))
        episodes = []

        for index in range(count):
            episode = {
                "episode_id": index + 1,
                "global_rank": index + 1,
                "zone_id": index + 1,
                "start_distance_m": 1000.0 + index * 100.0,
                "end_distance_m": 1080.0 + index * 100.0,
                "action_time_loss_s": 0.2 / (index + 1),
                "action_channels": ["throttle"],
            }
            if index < len(partial_results):
                episode["throttle_partial_lift_comparison"] = (
                    partial_results[index]
                )
            if index < len(sustained_results):
                episode[
                    "throttle_sustained_modulation_comparison"
                ] = sustained_results[index]
            episodes.append(episode)

        return {
            "reference_lap": reference_lap,
            "comparison_lap": comparison_lap,
            "objective_analysis": {
                "driver_action_episode_ranking": episodes,
            },
        }

    def partial_recurrence_repeated_additional():
        comparisons = [
            _mod_comparison(
                3,
                partial_results=[
                    _partial_result("throttle_a:08", 0, 1)
                ],
            ),
            _mod_comparison(
                2,
                partial_results=[
                    _partial_result("throttle_a:08", 0, 2)
                ],
            ),
            _mod_comparison(1),
        ]

        result = modulation_recurrence.build_partial_lift_recurrence(
            comparisons
        )
        pattern = result["patterns"][0]
        assert_equal(result["repeated_pattern_count"], 1, "repeated count")
        assert_equal(
            pattern["selected_state"],
            "additional_in_comparison",
            "selected state",
        )
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(pattern["count_difference_median"], 1.5, "median count")
        assert_equal(pattern["missing_comparison_count"], 1, "missing count")
        assert_equal(pattern["authorized_coaching"], False, "coaching")

    runner.run(
        "partial lift repeated additional count across comparisons",
        partial_recurrence_repeated_additional,
    )

    def partial_recurrence_fewer_with_neutral():
        comparisons = [
            _mod_comparison(
                3,
                partial_results=[
                    _partial_result("throttle_a:05", 1, 0)
                ],
            ),
            _mod_comparison(
                2,
                partial_results=[
                    _partial_result("throttle_a:05", 1, 1)
                ],
            ),
            _mod_comparison(
                1,
                partial_results=[
                    _partial_result("throttle_a:05", 2, 1)
                ],
            ),
        ]
        result = modulation_recurrence.build_partial_lift_recurrence(
            comparisons
        )
        pattern = result["patterns"][0]
        assert_equal(pattern["is_repeated"], True, "is repeated")
        assert_equal(
            pattern["selected_state"],
            "fewer_in_comparison",
            "selected state",
        )
        assert_equal(
            pattern["neutral_same_count_observation_count"],
            1,
            "neutral count",
        )
        assert_equal(
            pattern["recurrence_status"],
            "REPEATED_CONSISTENT",
            "status",
        )

    runner.run(
        "partial lift neutral same-count evidence is not contradiction",
        partial_recurrence_fewer_with_neutral,
    )

    def partial_recurrence_mixed_not_repeated():
        comparisons = [
            _mod_comparison(
                3,
                partial_results=[
                    _partial_result("throttle_a:04", 0, 1)
                ],
            ),
            _mod_comparison(
                2,
                partial_results=[
                    _partial_result("throttle_a:04", 1, 0)
                ],
            ),
        ]
        pattern = modulation_recurrence.build_partial_lift_recurrence(
            comparisons
        )["patterns"][0]
        assert_equal(pattern["is_repeated"], False, "is repeated")
        assert_equal(pattern["recurrence_status"], "NOT_REPEATED", "status")
        assert_equal(
            pattern["state_counts"],
            {
                "additional_in_comparison": 1,
                "fewer_in_comparison": 1,
            },
            "state counts",
        )

    runner.run(
        "partial lift mixed additional/fewer evidence is not promoted",
        partial_recurrence_mixed_not_repeated,
    )

    def partial_recurrence_duplicate_dedup():
        repeated = _partial_result("throttle_a:09", 0, 1)
        comparisons = [
            _mod_comparison(
                3,
                partial_results=[dict(repeated), dict(repeated)],
            ),
            _mod_comparison(
                2,
                partial_results=[
                    _partial_result("throttle_a:09", 0, 1)
                ],
            ),
        ]
        pattern = modulation_recurrence.build_partial_lift_recurrence(
            comparisons
        )["patterns"][0]
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(
            pattern["valid_observation_count"],
            2,
            "valid observations",
        )
        assert_true(
            max(
                row["duplicate_episode_count"]
                for row in pattern["observations"]
            ) == 1,
            "duplicate recorded",
        )

    runner.run(
        "partial lift duplicate episode assignment cannot inflate recurrence",
        partial_recurrence_duplicate_dedup,
    )

    def _sustained_result(
        reference_event_id,
        reference_classes,
        comparison_classes,
        comparison_event_id="cmp",
    ):
        reference_records = [
            {
                "sustained_modulation_id": f"ref:{index}",
                "classification": classification,
                "throttle_event_id": reference_event_id,
                "start_distance_m": 1000.0 + index * 5.0,
                "recovery_distance_m": 1080.0 + index * 5.0,
                "observational_only": True,
            }
            for index, classification in enumerate(
                reference_classes,
                start=1,
            )
        ]
        comparison_records = [
            {
                "sustained_modulation_id": f"cmp:{index}",
                "classification": classification,
                "throttle_event_id": comparison_event_id,
                "start_distance_m": 1000.0 + index * 5.0,
                "recovery_distance_m": 1080.0 + index * 5.0,
                "observational_only": True,
            }
            for index, classification in enumerate(
                comparison_classes,
                start=1,
            )
        ]
        return {
            "status": "VALID",
            "reference_modulation_count": len(reference_records),
            "comparison_modulation_count": len(comparison_records),
            "count_difference": (
                len(comparison_records) - len(reference_records)
            ),
            "comparison_has_additional_sustained_modulation": (
                len(comparison_records) > len(reference_records)
            ),
            "comparison_has_fewer_sustained_modulations": (
                len(comparison_records) < len(reference_records)
            ),
            "reference_modulations": reference_records,
            "comparison_modulations": comparison_records,
            "paired_event_context": [
                {
                    "throttle_pair_id": (
                        f"{reference_event_id}|{comparison_event_id}"
                    ),
                    "reference_event_id": reference_event_id,
                    "comparison_event_id": comparison_event_id,
                    "reference_modulation_count": len(reference_records),
                    "comparison_modulation_count": len(comparison_records),
                    "pair_cost": 10.0,
                }
            ],
            "observational_only": True,
            "affects_ranking": False,
            "authorized_coaching": False,
        }

    def sustained_recurrence_additional_classification():
        comparisons = [
            _mod_comparison(
                3,
                sustained_results=[
                    _sustained_result(
                        "throttle_a:06",
                        [],
                        ["deep_and_long"],
                    )
                ],
            ),
            _mod_comparison(
                2,
                sustained_results=[
                    _sustained_result(
                        "throttle_a:06",
                        [],
                        ["deep_and_long"],
                    )
                ],
            ),
            _mod_comparison(1),
        ]
        result = (
            modulation_recurrence
            .build_sustained_throttle_modulation_recurrence(comparisons)
        )
        pattern = result["patterns"][0]
        assert_equal(pattern["is_repeated"], True, "is repeated")
        assert_equal(
            pattern["selected_state"],
            "additional_in_comparison",
            "selected state",
        )
        assert_equal(
            pattern["dominant_classification"],
            "deep_and_long",
            "dominant classification",
        )
        assert_equal(
            pattern["dominant_classification_support_count"],
            2,
            "classification support",
        )
        assert_equal(
            pattern["repeated_classification"],
            True,
            "repeated classification",
        )

    runner.run(
        "sustained modulation repeated additional state preserves type",
        sustained_recurrence_additional_classification,
    )

    def sustained_recurrence_fewer():
        comparisons = [
            _mod_comparison(
                3,
                sustained_results=[
                    _sustained_result(
                        "throttle_a:10",
                        ["long"],
                        [],
                    )
                ],
            ),
            _mod_comparison(
                2,
                sustained_results=[
                    _sustained_result(
                        "throttle_a:10",
                        ["long"],
                        [],
                    )
                ],
            ),
        ]
        pattern = (
            modulation_recurrence
            .build_sustained_throttle_modulation_recurrence(comparisons)
            ["patterns"][0]
        )
        assert_equal(
            pattern["selected_state"],
            "fewer_in_comparison",
            "selected state",
        )
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(pattern["dominant_classification"], "long", "class")
        assert_equal(pattern["classification_consistent"], True, "consistent")

    runner.run(
        "sustained modulation repeated fewer state uses reference type",
        sustained_recurrence_fewer,
    )

    def sustained_recurrence_mixed_not_repeated():
        comparisons = [
            _mod_comparison(
                3,
                sustained_results=[
                    _sustained_result(
                        "throttle_a:12",
                        [],
                        ["deep"],
                    )
                ],
            ),
            _mod_comparison(
                2,
                sustained_results=[
                    _sustained_result(
                        "throttle_a:12",
                        ["deep"],
                        [],
                    )
                ],
            ),
        ]
        pattern = (
            modulation_recurrence
            .build_sustained_throttle_modulation_recurrence(comparisons)
            ["patterns"][0]
        )
        assert_equal(pattern["is_repeated"], False, "is repeated")
        assert_equal(pattern["recurrence_status"], "NOT_REPEATED", "status")

    runner.run(
        "sustained modulation mixed additional/fewer is not promoted",
        sustained_recurrence_mixed_not_repeated,
    )

    def sustained_duplicate_and_enrichment_preserve_session():
        repeated = _sustained_result(
            "throttle_a:14",
            [],
            ["deep_and_long"],
        )
        analysis = {
            "metadata": {"sentinel": "keep"},
            "comparisons": [
                _mod_comparison(
                    3,
                    sustained_results=[dict(repeated), dict(repeated)],
                ),
                _mod_comparison(
                    2,
                    sustained_results=[
                        _sustained_result(
                            "throttle_a:14",
                            [],
                            ["deep_and_long"],
                        )
                    ],
                ),
            ],
        }
        before = [
            [
                episode["episode_id"]
                for episode in comparison["objective_analysis"][
                    "driver_action_episode_ranking"
                ]
            ]
            for comparison in analysis["comparisons"]
        ]

        modulation_recurrence.enrich_analysis_with_throttle_modulation_recurrence(
            analysis
        )

        after = [
            [
                episode["episode_id"]
                for episode in comparison["objective_analysis"][
                    "driver_action_episode_ranking"
                ]
            ]
            for comparison in analysis["comparisons"]
        ]
        pattern = analysis["throttle_modulation_recurrence"][
            "sustained_throttle_modulation"
        ]["patterns"][0]
        assert_equal(after, before, "episode ranking")
        assert_equal(analysis["metadata"]["sentinel"], "keep", "metadata")
        assert_equal(pattern["support_count"], 2, "support count")
        assert_equal(pattern["valid_observation_count"], 2, "valid count")
        assert_true(
            max(
                row["duplicate_episode_count"]
                for row in pattern["observations"]
            ) == 1,
            "duplicate recorded",
        )
        config = analysis["throttle_modulation_recurrence"]["config"]
        assert_equal(config["affects_ranking"], False, "affects ranking")
        assert_equal(
            config["affects_session_priority"],
            False,
            "affects session priority",
        )

    runner.run(
        "sustained recurrence dedups and session enrichment preserves ranking",
        sustained_duplicate_and_enrichment_preserve_session,
    )

    # ========================================================
    # RECOVERY PATCHER
    # ========================================================
    section("RECOVERY PATCHER")

    def recovery_from_unpatched_source():
        sample = """import json
from sector_analysis import SectorAnalysis

def demo(zones, real_delta, comparison):
    if True:
        if True:
            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
            return objective_analysis

        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
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
    if True:
        if True:
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

        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
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
    if True:
        if True:
            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
            return objective_analysis

        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
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
