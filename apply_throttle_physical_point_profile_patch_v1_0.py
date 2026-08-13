from pathlib import Path
import re
import shutil
import sys


PATCHER_VERSION = "1.0.0"

IMPORT_LINE = (
    "from throttle_physical_point_profile_v1_0 import "
    "enrich_analysis_with_throttle_physical_point_profiles\n"
)

PROFILE_CALL = """        # Perfil unificado por punto físico de acelerador.
        # Sólo reúne hechos ya detectados; no modifica decisiones.
        enrich_analysis_with_throttle_physical_point_profiles(
            analysis_output,
        )

"""

MODULATION_CALL = """        # Recurrencia de partial lifts y modulaciones sostenidas.
        # Observacional: no modifica ranking, prioridad ni coaching.
        enrich_analysis_with_throttle_modulation_recurrence(
            analysis_output,
        )

"""

GLOBAL_VALIDATION_ANCHOR = """        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
"""

IMPORT_ANCHORS = (
    "from throttle_modulation_recurrence_v1_0 import "
    "enrich_analysis_with_throttle_modulation_recurrence\n",
    "from sector_analysis import SectorAnalysis\n",
)


def patch_text(original):
    text = original

    # Remove old/duplicate imports for the same hook.
    text = re.sub(
        r"^from\s+throttle_physical_point_profile[^\s]*\s+import\s+"
        r"enrich_analysis_with_throttle_physical_point_profiles\s*$\n?",
        "",
        text,
        flags=re.MULTILINE,
    )

    inserted = False
    for anchor in IMPORT_ANCHORS:
        if anchor in text:
            text = text.replace(anchor, anchor + IMPORT_LINE, 1)
            inserted = True
            break
    if not inserted:
        raise ValueError("No encontré ancla de import compatible.")

    # Remove canonical/legacy calls first for idempotence.
    text = text.replace(PROFILE_CALL, "")
    text = re.sub(
        r"\n(?P<indent>[ \t]*)"
        r"enrich_analysis_with_throttle_physical_point_profiles\(\n"
        r"(?P=indent)[ \t]+analysis_output,\n"
        r"(?P=indent)\)\n",
        "\n",
        text,
    )

    if MODULATION_CALL in text:
        text = text.replace(
            MODULATION_CALL,
            MODULATION_CALL + PROFILE_CALL,
            1,
        )
    elif GLOBAL_VALIDATION_ANCHOR in text:
        text = text.replace(
            GLOBAL_VALIDATION_ANCHOR,
            PROFILE_CALL + GLOBAL_VALIDATION_ANCHOR,
            1,
        )
    else:
        raise ValueError("No encontré hook session/global compatible.")

    compile(text, "<patched_analyze_telemetry>", "exec")
    return text


def verify_text(text):
    errors = []
    if text.count(IMPORT_LINE) != 1:
        errors.append(
            "import de throttle physical point profile ausente/duplicado"
        )
    count = text.count(
        "enrich_analysis_with_throttle_physical_point_profiles("
    )
    if count != 1:
        errors.append(
            f"hook throttle physical point profile aparece {count} veces"
        )
    return errors


def main():
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "analyze_telemetry.py"
    )
    if not target.is_file():
        raise SystemExit(f"No existe: {target}")

    original = target.read_text(encoding="utf-8")
    try:
        text = patch_text(original)
    except ValueError as exc:
        raise SystemExit(str(exc))

    errors = verify_text(text)
    if errors:
        raise SystemExit("ERROR DE VERIFICACIÓN:\n- " + "\n- ".join(errors))

    if text == original:
        print("Throttle Physical Point Profile v1.0 ya estaba instalado.")
        return 0

    backup = target.with_suffix(
        target.suffix + ".pre_throttle_physical_point_profile_v1_0.bak"
    )
    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")
    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print("Throttle Physical Point Profile v1.0: ACTIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
