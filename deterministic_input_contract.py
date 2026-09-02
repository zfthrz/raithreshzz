"""Deterministic input loading and lap-time validation contract."""

from __future__ import annotations

import json

from deterministic_coaching import safe_float, safe_int
from deterministic_comparison_render import format_lap_time, signed_seconds


def load_json(path):
    print()
    print("Cargando JSON:")
    print(path)
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("El JSON raíz debe ser un objeto.")
    return data


def build_lap_time_map(data):
    result = {}
    metadata_times = data.get("metadata", {}).get("lap_times_s", {})
    if isinstance(metadata_times, dict):
        for lap, duration in metadata_times.items():
            lap_id = safe_int(lap)
            duration_s = safe_float(duration)
            if lap_id is not None and duration_s is not None and duration_s > 0:
                result[lap_id] = duration_s
    laps = data.get("laps", [])
    if isinstance(laps, list):
        for record in laps:
            if not isinstance(record, dict):
                continue
            lap_id = safe_int(record.get("lap"))
            duration_s = safe_float(record.get("duration"))
            if lap_id is not None and duration_s is not None and duration_s > 0:
                result[lap_id] = duration_s
    return result


def resolve_comparison_laps(comparison, metadata):
    reference_lap = safe_int(comparison.get("reference_lap"))
    comparison_lap = safe_int(comparison.get("comparison_lap"))
    if reference_lap is None:
        reference_lap = safe_int(comparison.get("lap_a"))
    if comparison_lap is None:
        comparison_lap = safe_int(comparison.get("lap_b"))
    if reference_lap is None:
        reference_lap = safe_int(metadata.get("reference_lap"))
    if reference_lap is None or comparison_lap is None:
        raise ValueError(
            "No fue posible determinar reference_lap/comparison_lap de una comparación."
        )
    return reference_lap, comparison_lap


def validate_data_model(data):
    print()
    print("Validando modelo de datos...")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("El JSON no contiene metadata válida.")
    comparisons = data.get("comparisons")
    if not isinstance(comparisons, list):
        raise ValueError("El JSON no contiene comparisons como lista.")
    if (
        metadata.get("lap_comparison_model") != "same_vehicle_different_laps"
        and metadata.get("same_vehicle") is not True
    ):
        raise ValueError(
            "El JSON no corresponde al modelo mismo vehículo / distintas vueltas."
        )
    print("Modelo confirmado:")
    print("mismo vehículo / distintas vueltas")
    print()
    print(f"Analyze Telemetry version: {metadata.get('analysis_version', 'unknown')}")
    print(f"Vuelta de referencia: {metadata.get('reference_lap')}")
    print(f"Vueltas válidas: {metadata.get('valid_laps', [])}")
    print(f"Vueltas descartadas: {metadata.get('discarded_laps', [])}")
    print(f"Comparaciones disponibles: {len(comparisons)}")
    if metadata.get("temporal_validation_status") is not None:
        print(f"Validación temporal: {metadata.get('temporal_validation_status')}")
    if metadata.get("objective_analysis_validation") is not None:
        print(f"Validación objetiva: {metadata.get('objective_analysis_validation')}")
    return metadata, comparisons


def validate_lap_times(data, metadata, comparisons):
    print()
    print("Validando tiempos de vuelta...")
    lap_times = build_lap_time_map(data)
    if not lap_times:
        raise RuntimeError("No se encontraron tiempos absolutos de vuelta.")
    for lap in sorted(lap_times):
        print(f"  lap {lap}: {format_lap_time(lap_times[lap])}")
    print()
    for comparison in comparisons:
        reference_lap, comparison_lap = resolve_comparison_laps(
            comparison, metadata
        )
        reference_time = safe_float(comparison.get("reference_time_s"))
        comparison_time = safe_float(comparison.get("comparison_time_s"))
        real_delta = safe_float(comparison.get("comparison_minus_reference_s"))
        if reference_time is None:
            reference_time = lap_times.get(reference_lap)
        if comparison_time is None:
            comparison_time = lap_times.get(comparison_lap)
        if reference_time is None or comparison_time is None:
            raise RuntimeError(
                "Tiempo absoluto faltante para comparación "
                f"{reference_lap} -> {comparison_lap}"
            )
        expected_delta = comparison_time - reference_time
        if real_delta is None:
            real_delta = expected_delta
        error = real_delta - expected_delta
        print(f"Comparación: {reference_lap} -> {comparison_lap}")
        print(f"  Tiempo A: {format_lap_time(reference_time)}")
        print(f"  Tiempo B: {format_lap_time(comparison_time)}")
        print(f"  Delta real: {signed_seconds(real_delta)}")
        print(f"  Verificación: error={error:+.6f} s")
        if abs(error) > 0.001:
            raise RuntimeError(
                "LAP_TIME_VALIDATION_FAILED "
                f"{reference_lap} -> {comparison_lap}: {error:+.6f} s"
            )
    print()
    print("Validación temporal completa.")
    return lap_times
