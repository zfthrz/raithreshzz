import importlib


def test_known_throttle_profiles_render_as_driver_actions_with_safe_fallback():
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_ACTIONABILITY_POLICY_VERSION == "1.7"

        assert module._driver_facing_throttle_profile_text(
            "aplicación alta breve"
        ) == "hacé una aplicación alta y breve de acelerador como en la referencia"
        assert module._driver_facing_throttle_profile_text(
            "reaplicación sostenida sin volver a soltar dentro de la zona"
        ) == "reaplicá y sostené el acelerador como en la referencia"
        assert module._driver_facing_throttle_profile_text(
            "aplicación parcial breve → acelerador liberado → reaplicación sostenida"
        ) == (
            "hacé una aplicación parcial y breve de acelerador; después, "
            "soltá el acelerador; después, reaplicá y sostené el acelerador "
            "como en la referencia"
        )
        assert module._driver_facing_throttle_profile_text(
            "forma futura no reconocida"
        ) == (
            "replicá la secuencia de acelerador de la referencia: "
            "forma futura no reconocida"
        )

        cues = module.build_driver_cues_for_plan_item({
            "reference_action_profiles": [{
                "channel": "throttle",
                "shape_summary": "aplicación media breve",
            }],
        })
        assert cues[0]["text"] == (
            "hacé una aplicación media y breve de acelerador como en la referencia"
        )


def test_known_throttle_profiles_remain_driver_facing_when_anchored_to_points():
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)

        both_points = module.build_driver_cues_for_plan_item({
            "throttle_onset_patterns": [{
                "coaching_magnitude_m": 12,
                "coaching_direction": "earlier",
            }],
            "throttle_release_patterns": [{
                "coaching_magnitude_m": 8,
                "coaching_direction": "later",
            }],
            "reference_action_profiles": [{
                "channel": "throttle",
                "shape_summary": "aplicación alta breve",
            }],
        })
        assert both_points[0]["text"] == (
            "reaplicá el acelerador aproximadamente 12 m más temprano y "
            "soltá el acelerador aproximadamente 8 m más tarde"
        )
        assert both_points[1]["text"] == (
            "hacé una aplicación alta y breve de acelerador como en la referencia"
        )

        onset_only = module.build_driver_cues_for_plan_item({
            "throttle_onset_patterns": [{
                "coaching_magnitude_m": 10,
                "coaching_direction": "later",
            }],
            "reference_action_profiles": [{
                "channel": "throttle",
                "shape_summary": "aplicación parcial breve",
            }],
        })
        assert onset_only[0]["text"] == (
            "reaplicá el acelerador aproximadamente 10 m más tarde"
        )
        assert onset_only[1]["text"] == (
            "hacé una aplicación parcial y breve de acelerador como en la referencia"
        )

        release_only = module.build_driver_cues_for_plan_item({
            "throttle_release_patterns": [{
                "coaching_magnitude_m": 6,
                "coaching_direction": "earlier",
            }],
            "reference_action_profiles": [{
                "channel": "throttle",
                "shape_summary": "aplicación media breve",
            }],
        })
        assert release_only[0]["text"] == (
            "soltá el acelerador aproximadamente 6 m más temprano"
        )
        assert release_only[1]["text"] == (
            "hacé una aplicación media y breve de acelerador como en la referencia"
        )
