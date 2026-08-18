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


def test_mixed_zone_brake_wins_over_throttle_region():
    """
    Brake point(2) vs throttle region(5) → brake debe ordenar primero.

    La regla v1.9 channel-neutral: mejor soporte de punto físico precede a región
    sin punto repetido.  Brake(tier 0) < throttle_region(tier 3).
    """
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        # Brake item with a repeated point (evidence_tier=0)
        brake = _repeated_point_item("brake", 2, 5, 1200.0)

        # Throttle region without a repeated point (evidence_tier=3)
        # This item has no point patterns with status="REPEATED", so it falls to tier 3.
        throttle_region = {
            "kind": "repeated_region",
            "comparison_count": 5,
            "start_distance_m": 1200.0,
            "end_distance_m": 1300.0,
            # No braking_point_patterns or throttle_onset_patterns with REPEATED status
            # so evidence_tier will be 3 (lowest)
        }

        # Brake (tier 0) should sort before throttle region (tier 3)
        assert module._session_plan_sort_key(brake) < module._session_plan_sort_key(
            throttle_region
        )


def test_sustained_throttle_modulation_sort_key():
    """Modulación sostenida debe tener evidence_tier=2, menor que punto físico (evidence_tier=0)."""
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        profile = {
            "kind": "reference_action_profile",
            "comparison_count": 3,
            "start_distance_m": 1500.0,
            "end_distance_m": 1600.0,
            "reference_action_profiles": [{
                "channel": "throttle",
                "shape_summary": "reaplicación sostenida sin volver a soltar dentro de la zona",
            }],
        }
        repeated_point = _repeated_point_item("throttle", 2, 5, 1200.0)

        assert module._session_plan_sort_key(repeated_point) < module._session_plan_sort_key(profile)