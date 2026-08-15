import importlib


def _repeated_point_item(channel, point_support, region_support, start_m):
    field = {
        "brake": "braking_point_patterns",
        "throttle": "throttle_onset_patterns",
    }[channel]
    return {
        "kind": "repeated_region",
        "comparison_count": region_support,
        "start_distance_m": start_m,
        "end_distance_m": start_m + 100.0,
        field: [
            {
                "status": "REPEATED",
                "comparison_count": point_support,
                "authorized_numeric_coaching": True,
                "coaching_direction": "later",
                "coaching_magnitude_m": 10,
            }
        ],
    }


def test_repeated_point_support_precedes_region_recurrence_without_channel_bias():
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        brake_better_supported = _repeated_point_item("brake", 3, 4, 1200.0)
        throttle_broader_region = _repeated_point_item("throttle", 2, 5, 2800.0)
        assert module._session_plan_sort_key(brake_better_supported) < module._session_plan_sort_key(
            throttle_broader_region
        )

        throttle_better_supported = _repeated_point_item("throttle", 3, 4, 2800.0)
        brake_broader_region = _repeated_point_item("brake", 2, 5, 1200.0)
        assert module._session_plan_sort_key(throttle_better_supported) < module._session_plan_sort_key(
            brake_broader_region
        )
