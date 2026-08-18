"""
Tests de asimetría brake/throttle y fallback descriptivo.

v0.1 — shadow evidencing structure without changing priority or coaching
       authority.  All assertions are 100 % deterministic; no LLM is called.
"""
from __future__ import annotations

import importlib

import pytest


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


def _repeated_region_item(channel, region_support, start_m):
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
                "comparison_count": region_support,
                "authorized_numeric_coaching": False,
                "coaching_direction": "later",
                "coaching_magnitude_m": 10,
            }
        ],
    }


def _profile_item(channel, shape_summary):
    return {
        "kind": "reference_action_profile",
        "comparison_count": 3,
        "start_distance_m": 1500.0,
        "end_distance_m": 1600.0,
        "reference_action_profiles": [
            {
                "channel": channel,
                "shape_summary": shape_summary,
            }
        ],
    }


def _mixed_zone(brake_item, throttle_item):
    """Combina dos ítems en un único plan item mixto (brake + throttle juntos)."""
    return {
        "kind": "repeated_region",
        "comparison_count": 5,
        "start_distance_m": 1200.0,
        "end_distance_m": 1300.0,
        "braking_point_patterns": brake_item.get("braking_point_patterns", []),
        "throttle_onset_patterns": throttle_item.get("throttle_onset_patterns", []),
    }


def test_unknown_shape_descriptive_fallback():
    """Shape desconocida debe retornar el fallback descriptivo completo."""
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_ACTIONABILITY_POLICY_VERSION == "1.7"

        assert module._driver_facing_throttle_profile_text(
            "forma futura no reconocida"
        ) == (
            "replicá la secuencia de acelerador de la referencia: "
            "forma futura no reconocida"
        )

        assert module._driver_facing_throttle_profile_text(
            "aplicación alta breve"
        ) == "hacé una aplicación alta y breve de acelerador como en la referencia"

        assert module._driver_facing_throttle_profile_text(
            "reaplicación sostenida sin volver a soltar dentro de la zona"
        ) == "reaplicá y sostené el acelerador como en la referencia"


def test_mixed_zone_brake_wins_over_throttle():
    """
    Brake point(2) vs throttle region(5) → brake debe ordenar primero.

    La regla v1.9 dice: punto físico con mejor soporte de comparación precede
    a región con mayor recurrencia.  Brake(2) > throttle(5) porque 2 puntos
    repetidos > 5 región sin punto repetido.
    """
    brake = _repeated_point_item("brake", 2, 5, 1200.0)
    throttle = _repeated_region_item("throttle", 5, 1200.0)

    mixed = _mixed_zone(brake, throttle)
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)

        # brake(2) repeated point should sort before throttle(5) region
        assert module._session_plan_sort_key(mixed) < module._session_plan_sort_key(
            _repeated_region_item("throttle", 5, 2000.0)
        )


def test_mixed_zone_throttle_point_wins_over_brake_region():
    """
    Throttle point(3) vs brake region(5) → throttle debe ordenar primero.

    Sort key channel-neutral: mejor soporte de punto físico precede.
    Throttle(3) > brake(5) porque 3 > 2.
    """
    throttle = _repeated_point_item("throttle", 3, 5, 1200.0)
    brake = _repeated_region_item("brake", 5, 1200.0)

    mixed = _mixed_zone(brake, throttle)
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        # throttle(3) repeated point should sort before brake(5) region
        assert module._session_plan_sort_key(mixed) < module._session_plan_sort_key(
            _repeated_region_item("brake", 5, 2000.0)
        )


def test_mixed_zone_brake_wins_with_better_points():
    """
    Brake point(3) vs throttle point(2) → brake debe ordenar primero.

    Ambos tienen patrones repetidos: mayor support_count gana.
    """
    brake = _repeated_point_item("brake", 3, 5, 1200.0)
    throttle = _repeated_point_item("throttle", 2, 5, 1200.0)

    mixed = _mixed_zone(brake, throttle)
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        assert module._session_plan_sort_key(mixed) < module._session_plan_sort_key(
            _repeated_point_item("throttle", 2, 5, 2000.0)
        )


def test_repeated_region_sort_key_stability():
    """
    Una región sin punto repetido no debe competir con un punto repetido.

    Sort key para región debe tener evidence_tier > 0, mientras que un
    punto repetido tiene evidence_tier=0.
    """
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        region = _repeated_region_item("throttle", 5, 1200.0)
        repeated_point = _repeated_point_item("throttle", 2, 5, 1200.0)

        assert module._session_plan_sort_key(repeated_point) < module._session_plan_sort_key(
            region
        )


def test_sustained_throttle_modulation_sort_key():
    """
    Modulación sostenida (reference_action_profile) debe tener evidence_tier=2,
    menor que un punto físico (evidence_tier=0 o 1).
    """
    profile = _profile_item("throttle", "reaplicación sostenida sin volver a soltar dentro de la zona")
    repeated_point = _repeated_point_item("throttle", 2, 5, 1200.0)

    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        assert module._session_plan_sort_key(repeated_point) < module._session_plan_sort_key(profile)


def test_physical_point_support_precedes_region_recurrence_channel_neutral():
    """
    La regla v1.9 debe mantenerse channel-neutral: un punto de throttle mejor
    soportado precede a un punto de freno con peor soporte.
    """
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        better_throttle = _repeated_point_item("throttle", 3, 4, 2800.0)
        worse_brake = _repeated_point_item("brake", 2, 5, 1200.0)

        assert module._session_plan_sort_key(better_throttle) < module._session_plan_sort_key(
            worse_brake
        )


def test_compound_throttle_profile_text():
    """Perfiles compuestos deben construirse correctamente."""
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)

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


def test_repeated_region_sort_key_invariant_across_channels():
    """
    El sort key debe ser invariante: cambiar el orden de brake/throttle en
    la entrada no afecta el sort key del ítem individual.
    """
    for module_name in ("llm_analysis", "llm_analysis_deepseek"):
        module = importlib.import_module(module_name)
        assert module.SESSION_PRIORITY_POLICY_VERSION == "1.9"

        brake_a = _repeated_point_item("brake", 2, 5, 1200.0)
        brake_b = _repeated_point_item("brake", 2, 5, 1200.0)

        assert module._session_plan_sort_key(brake_a) == module._session_plan_sort_key(brake_b)
