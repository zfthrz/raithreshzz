import importlib


def test_known_throttle_profiles_render_as_driver_actions_with_safe_fallback():
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_ACTIONABILITY_POLICY_VERSION == "1.5"

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
