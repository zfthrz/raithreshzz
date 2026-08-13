from pathlib import Path
import re
import shutil
import sys


RECOVERY_PATCH_VERSION = "2026.08.13-v6"

BRAKE_IMPORT = (
    "from braking_point_v2_1 import enrich_objective_with_braking_points\n"
)
THROTTLE_IMPORT = (
    "from throttle_point_v1_2_1 import enrich_objective_with_throttle_points\n"
)
SEQUENCE_IMPORT = (
    "from throttle_episode_sequence_v1_0 import "
    "enrich_objective_with_throttle_event_sequences\n"
)
SUSTAINED_IMPORT = (
    "from throttle_sustained_modulation_v1_0 import "
    "enrich_objective_with_sustained_throttle_modulations\n"
)
RECURRENCE_IMPORT = (
    "from full_throttle_recurrence_v1_0 import "
    "enrich_analysis_with_full_throttle_attainment_recurrence\n"
)
MODULATION_RECURRENCE_IMPORT = (
    "from throttle_modulation_recurrence_v1_0 import "
    "enrich_analysis_with_throttle_modulation_recurrence\n"
)
PROFILE_IMPORT = (
    "from throttle_physical_point_profile_v1_0 import "
    "enrich_analysis_with_throttle_physical_point_profiles\n"
)
GATE_IMPORT = (
    "from throttle_coaching_evidence_gate_v1_0 import "
    "enrich_analysis_with_throttle_coaching_evidence_gate\n"
)

IMPORT_ANCHOR = (
    "from sector_analysis import SectorAnalysis\n"
)

BUILD_BLOCK = """            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
"""

CANONICAL_HOOKS = """
            # Punto de frenada determinista (braking_point_v2_1.py).
            # Sólo enriquece episodios; no modifica ranking ni deltas.
            enrich_objective_with_braking_points(
                comparison,
                objective_analysis,
            )

            # Puntos de acelerador deterministas
            # (throttle_point_v1_2_1.py).
            # Onset/release mantienen la lógica 1.1; full-throttle y
            # partial-lift son observacionales.
            enrich_objective_with_throttle_points(
                comparison,
                objective_analysis,
            )

            # Secuencia física de eventos de acelerador por episodio.
            # Observacional: no modifica ranking ni coaching.
            enrich_objective_with_throttle_event_sequences(
                comparison,
                objective_analysis,
            )

            # Modulación sostenida de acelerador.
            # Observacional: no modifica ranking ni coaching.
            enrich_objective_with_sustained_throttle_modulations(
                comparison,
                objective_analysis,
            )
"""

CANONICAL_SESSION_HOOKS = """        # Recurrencia de full-throttle attainment entre vueltas.
        # Observacional: no modifica ranking, prioridad ni coaching.
        enrich_analysis_with_full_throttle_attainment_recurrence(
            analysis_output,
        )

        # Recurrencia de partial lifts y modulaciones sostenidas.
        # Observacional: no modifica ranking, prioridad ni coaching.
        enrich_analysis_with_throttle_modulation_recurrence(
            analysis_output,
        )

        # Perfil unificado por punto físico de acelerador.
        # Sólo reúne hechos ya detectados; no modifica decisiones.
        enrich_analysis_with_throttle_physical_point_profiles(
            analysis_output,
        )

        # Gate de evidencia para coaching de acelerador.
        # Shadow mode: no modifica ranking, prioridad ni coaching activo.
        enrich_analysis_with_throttle_coaching_evidence_gate(
            analysis_output,
        )

"""

GLOBAL_VALIDATION_ANCHOR = """        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
"""

TARGET_IMPORTS = (
    BRAKE_IMPORT,
    THROTTLE_IMPORT,
    SEQUENCE_IMPORT,
    SUSTAINED_IMPORT,
    RECURRENCE_IMPORT,
    MODULATION_RECURRENCE_IMPORT,
    PROFILE_IMPORT,
    GATE_IMPORT,
)

HOOK_NAMES = (
    "enrich_objective_with_braking_points",
    "enrich_objective_with_throttle_points",
    "enrich_objective_with_throttle_event_sequences",
    "enrich_objective_with_sustained_throttle_modulations",
)

SESSION_HOOK_NAMES = (
    "enrich_analysis_with_full_throttle_attainment_recurrence",
    "enrich_analysis_with_throttle_modulation_recurrence",
    "enrich_analysis_with_throttle_physical_point_profiles",
    "enrich_analysis_with_throttle_coaching_evidence_gate",
)


def _remove_versioned_imports(text):
    patterns = (
        r"^from\s+braking_point[^\s]*\s+import\s+"
        r"enrich_objective_with_braking_points\s*$",
        r"^from\s+throttle_point[^\s]*\s+import\s+"
        r"enrich_objective_with_throttle_points\s*$",
        r"^from\s+throttle_episode_sequence[^\s]*\s+import\s+"
        r"enrich_objective_with_throttle_event_sequences\s*$",
        r"^from\s+throttle_sustained_modulation[^\s]*\s+import\s+"
        r"enrich_objective_with_sustained_throttle_modulations\s*$",
        r"^from\s+full_throttle_recurrence[^\s]*\s+import\s+"
        r"enrich_analysis_with_full_throttle_attainment_recurrence\s*$",
        r"^from\s+throttle_modulation_recurrence[^\s]*\s+import\s+"
        r"enrich_analysis_with_throttle_modulation_recurrence\s*$",
        r"^from\s+throttle_physical_point_profile[^\s]*\s+import\s+"
        r"enrich_analysis_with_throttle_physical_point_profiles\s*$",
        r"^from\s+throttle_coaching_evidence_gate[^\s]*\s+import\s+"
        r"enrich_analysis_with_throttle_coaching_evidence_gate\s*$",
    )

    for pattern in patterns:
        text = re.sub(
            pattern + r"\n?",
            "",
            text,
            flags=re.MULTILINE,
        )

    return text


def _remove_hook_calls(text):
    for name in HOOK_NAMES:
        pattern = re.compile(
            r"\n(?P<indent>[ \t]*)"
            + re.escape(name)
            + r"\(\n"
            r"(?P=indent)[ \t]+comparison,\n"
            r"(?P=indent)[ \t]+objective_analysis,\n"
            r"(?P=indent)\)\n"
        )

        text = pattern.sub(
            "\n",
            text,
        )

    return text


def _remove_session_hook_calls(text):
    text = text.replace(
        CANONICAL_SESSION_HOOKS,
        "",
    )

    for name in SESSION_HOOK_NAMES:
        pattern = re.compile(
            r"\n(?P<indent>[ \t]*)"
            + re.escape(name)
            + r"\(\n"
            r"(?P=indent)[ \t]+analysis_output,\n"
            r"(?P=indent)\)\n"
        )
        text = pattern.sub(
            "\n",
            text,
        )

    return text


def patch_text(original):
    text = original

    text = _remove_versioned_imports(
        text
    )

    if IMPORT_ANCHOR not in text:
        raise ValueError(
            "No encontré 'from sector_analysis import SectorAnalysis'."
        )

    imports = (
        BRAKE_IMPORT
        + THROTTLE_IMPORT
        + SEQUENCE_IMPORT
        + SUSTAINED_IMPORT
        + RECURRENCE_IMPORT
        + MODULATION_RECURRENCE_IMPORT
        + PROFILE_IMPORT
        + GATE_IMPORT
    )

    # Normalizar el espacio vertical alrededor del bloque de imports para
    # que volver a aplicar el recovery produzca exactamente el mismo texto.
    text = re.sub(
        re.escape(IMPORT_ANCHOR) + r"\n*",
        IMPORT_ANCHOR,
        text,
        count=1,
    )

    text = text.replace(
        IMPORT_ANCHOR,
        IMPORT_ANCHOR + imports + "\n",
        1,
    )

    # Quitar primero nuestro bloque canónico completo si ya existía.
    # Esto hace el patch estrictamente idempotente también a nivel texto.
    text = text.replace(
        CANONICAL_HOOKS,
        "",
    )

    text = _remove_hook_calls(
        text
    )

    if BUILD_BLOCK not in text:
        raise ValueError(
            "No encontré el bloque build_objective_analysis esperado."
        )

    text = text.replace(
        BUILD_BLOCK,
        BUILD_BLOCK + CANONICAL_HOOKS,
        1,
    )

    text = _remove_session_hook_calls(
        text
    )

    if GLOBAL_VALIDATION_ANCHOR not in text:
        raise ValueError(
            "No encontré el bloque VALIDACIÓN GLOBAL esperado."
        )

    text = text.replace(
        GLOBAL_VALIDATION_ANCHOR,
        CANONICAL_SESSION_HOOKS + GLOBAL_VALIDATION_ANCHOR,
        1,
    )

    compile(
        text,
        "<patched_analyze_telemetry>",
        "exec",
    )

    return text


def verify_text(text):
    errors = []

    for import_line in TARGET_IMPORTS:
        count = text.count(
            import_line
        )
        if count != 1:
            errors.append(
                f"import esperado {count} veces: "
                f"{import_line.strip()}"
            )

    for hook_name in HOOK_NAMES:
        count = text.count(
            hook_name + "("
        )

        # One occurrence in the call; imports do not contain "(".
        if count != 1:
            errors.append(
                f"hook {hook_name} aparece {count} veces"
            )

    for session_hook_name in SESSION_HOOK_NAMES:
        session_count = text.count(
            session_hook_name + "("
        )
        if session_count != 1:
            errors.append(
                f"hook {session_hook_name} aparece {session_count} veces"
            )

    return errors


def main():
    args = [
        arg
        for arg in sys.argv[1:]
        if arg != "--check"
    ]
    check_only = (
        "--check" in sys.argv[1:]
    )

    target = Path(
        args[0]
        if args
        else "analyze_telemetry.py"
    )

    if not target.is_file():
        raise SystemExit(
            f"No existe: {target}"
        )

    original = target.read_text(
        encoding="utf-8"
    )

    if check_only:
        errors = verify_text(
            original
        )

        if errors:
            print(
                "OBJECTIVE PYTHON RECOVERY: NOT READY"
            )
            for error in errors:
                print(
                    f"  - {error}"
                )
            return 1

        print(
            "OBJECTIVE PYTHON RECOVERY: READY"
        )
        return 0

    try:
        text = patch_text(
            original
        )
    except ValueError as exc:
        raise SystemExit(
            str(exc)
        )

    errors = verify_text(
        text
    )

    if errors:
        raise SystemExit(
            "ERROR DE VERIFICACIÓN:\n- "
            + "\n- ".join(errors)
        )

    if text == original:
        print(
            "Objective Python ya estaba en el estado esperado."
        )
        return 0

    backup = target.with_suffix(
        target.suffix
        + ".pre_objective_python_recovery.bak"
    )

    if not backup.exists():
        shutil.copy2(
            target,
            backup,
        )

    target.write_text(
        text,
        encoding="utf-8",
    )

    print(
        "Objective Python recovery aplicado."
    )
    print(
        f"Target: {target}"
    )
    print(
        f"Backup: {backup}"
    )
    print(
        "  Brake Point: 2.1"
    )
    print(
        "  Throttle Point: 1.2.1 / schema 1.2"
    )
    print(
        "  Throttle Episode Sequence: 1.0"
    )
    print(
        "  Throttle Sustained Modulation: 1.0"
    )
    print(
        "  Full Throttle Attainment Recurrence: 1.0"
    )
    print(
        "  Throttle Modulation Recurrence: 1.0"
    )
    print(
        "  Throttle Physical Point Profile: 1.0"
    )
    print(
        "  Throttle Coaching Evidence Gate: 1.0 / SHADOW"
    )
    print(
        "  LLM Analysis: NO MODIFICADO"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
