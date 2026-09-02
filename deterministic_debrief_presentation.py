"""Console presentation for the deterministic debrief runtime."""

from __future__ import annotations

from collections.abc import Callable

from deterministic_coaching import safe_int
from deterministic_comparison_render import format_lap_time, meters, signed_seconds
from deterministic_debrief_runtime import DebriefPresentation


def print_header(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def build_console_presentation(
    *,
    model_name: str,
    context_size: int,
    temperature: float,
    usage_summary: Callable[[], None],
) -> DebriefPresentation:
    """Build the historical console hooks without importing an LLM backend."""

    def start():
        print_header("RACE ENGINEER - DETERMINISTIC DEBRIEF v3.10.8.5.4")

    def model_banner():
        print()
        print(f"Runtime: Python determinista · compatibilidad {model_name}")
        print(f"Contexto compatible: {context_size}")
        print(f"Temperatura registrada: {temperature}")
        print()

    def track_status(context):
        if context.get("status") == "ACTIVE":
            print(
                "Ubicación de pista: "
                f"{context.get('profile_id')} [{context.get('profile_status')}]"
            )
        else:
            print(
                "Ubicación de pista: "
                f"{context.get('status')} "
                "(se conservan metros sin nombres de curva)"
            )
        print()

    def architecture():
        print("Arquitectura v3.10.8.5.4:")
        print(
            "Python = hechos + estructura + validación + gates + ubicación + "
            "priorización + coaching + render"
        )
        print("Transporte LLM = inaccesible desde el runtime normal")
        print()

    def quality_gate(gate):
        excluded = safe_int(gate.get("excluded_count")) or 0
        retained = safe_int(gate.get("retained_statistical_outlier_count")) or 0
        if retained:
            print(
                f"Gate de calidad de comparación: {retained} outlier(s) "
                "estadístico(s) conservado(s) para coaching al no presentar "
                "severidad local suficiente para excluirlos."
            )
            print()
        if excluded:
            noun = "comparación" if excluded == 1 else "comparaciones"
            verb = "alimentará" if excluded == 1 else "alimentarán"
            print(
                f"Gate de calidad de comparación: {excluded} {noun} "
                f"globalmente no representativa(s) no {verb} el plan de sesión."
            )
            print()

    def comparison_header(index):
        print_header(f"COMPARACIÓN {index}")

    def comparison_facts(comparison, prepared):
        print(
            f"Comparación: {comparison['reference_lap']} -> "
            f"{comparison['comparison_lap']}"
        )
        print(f"Tiempo A: {format_lap_time(comparison['reference_time_s'])}")
        print(f"Tiempo B: {format_lap_time(comparison['comparison_time_s'])}")
        print(
            "Delta real: "
            f"{signed_seconds(comparison['comparison_minus_reference_s'])}"
        )
        print(
            "Episodios detectados: "
            f"{len(prepared.detected_episode_catalog)}"
        )
        print(
            "Episodios elegibles para coaching: "
            f"{len(prepared.episode_catalog)}"
        )
        print(f"Pérdidas anómalas excluidas: {len(prepared.excluded_anomalies)}")
        for anomaly in prepared.excluded_anomalies:
            print(
                f"  - episodio #{anomaly.get('episode_id')} · "
                f"{meters(anomaly.get('start_distance_m'))}–"
                f"{meters(anomaly.get('end_distance_m'))} · "
                f"{signed_seconds(anomaly.get('local_loss_s'))}"
            )

    def comparison_route(prepared):
        print()
        if not prepared.session_plan_eligible:
            print(
                "Comparación excluida por el gate global de calidad; se conserva "
                "el ground truth sin alimentar el plan."
            )
        elif prepared.episode_catalog:
            print("Generando interpretación y ranking deterministas...")
        else:
            print(
                "Todos los episodios fueron excluidos por el gate de anomalías; "
                "no alimentan el coaching."
            )

    def comparison_rejected(comparison, errors):
        print_header("DETERMINISTIC RESPONSE REJECTED")
        print(
            f"Comparación {comparison['reference_lap']} -> "
            f"{comparison['comparison_lap']}"
        )
        for error in errors:
            print(f"  - {error}")

    def comparison_validated(execution):
        print(
            "Respuesta validada en "
            f"{execution.validated['attempts']} intento(s)."
        )

    def synthesis_header():
        print_header("SÍNTESIS GLOBAL")

    def session_facts(facts):
        print(
            "Agregación determinista de coaching: "
            f"{facts['priority_finding_count']} hallazgo(s) prioritario(s)."
        )

    def synthesis_request():
        print("Generando síntesis estructurada determinista...")

    def synthesis_rejected(errors):
        print_header("GLOBAL RESPONSE REJECTED")
        for error in errors or []:
            print(f"  - {error}")

    def final_analysis(analysis):
        print()
        print_header("ANÁLISIS FINAL")
        print(analysis)

    def saved_result(path):
        print()
        print_header("RESULTADO GUARDADO")
        print(path)

    def complete():
        print()
        print_header("ANALYSIS COMPLETE")

    return DebriefPresentation(
        start=start,
        model_banner=model_banner,
        track_status=track_status,
        architecture=architecture,
        quality_gate=quality_gate,
        comparison_header=comparison_header,
        comparison_facts=comparison_facts,
        comparison_route=comparison_route,
        comparison_rejected=comparison_rejected,
        comparison_validated=comparison_validated,
        synthesis_header=synthesis_header,
        session_facts=session_facts,
        synthesis_request=synthesis_request,
        synthesis_rejected=synthesis_rejected,
        usage_summary=usage_summary,
        final_analysis=final_analysis,
        saved_result=saved_result,
        complete=complete,
    )
