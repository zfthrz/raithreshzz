from pathlib import Path
import shutil
import sys


PATCHER_VERSION = "1.0.0"

IMPORT_LINE = (
    "from throttle_modulation_recurrence_v1_0 import "
    "enrich_analysis_with_throttle_modulation_recurrence\n"
)

SESSION_CALL = """        # Recurrencia de partial lifts y modulaciones sostenidas.
        # Observacional: no modifica ranking, prioridad ni coaching.
        enrich_analysis_with_throttle_modulation_recurrence(
            analysis_output,
        )

"""

FULL_THROTTLE_CALL = """        # Recurrencia de full-throttle attainment entre vueltas.
        # Observacional: no modifica ranking, prioridad ni coaching.
        enrich_analysis_with_full_throttle_attainment_recurrence(
            analysis_output,
        )

"""

GLOBAL_VALIDATION_ANCHOR = """        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
"""

IMPORT_ANCHORS = (
    "from full_throttle_recurrence_v1_0 import "
    "enrich_analysis_with_full_throttle_attainment_recurrence\n",
    "from sector_analysis import SectorAnalysis\n",
)


def main():
    target = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "analyze_telemetry.py"
    )

    if not target.is_file():
        raise SystemExit(f"No existe: {target}")

    original = target.read_text(encoding="utf-8")
    text = original

    while text.count(IMPORT_LINE) > 1:
        text = text.replace(IMPORT_LINE, "", 1)

    if IMPORT_LINE not in text:
        inserted = False
        for anchor in IMPORT_ANCHORS:
            if anchor in text:
                text = text.replace(
                    anchor,
                    anchor + IMPORT_LINE,
                    1,
                )
                inserted = True
                break

        if not inserted:
            raise SystemExit(
                "No encontré ancla de import compatible."
            )

    if SESSION_CALL not in text:
        if FULL_THROTTLE_CALL in text:
            text = text.replace(
                FULL_THROTTLE_CALL,
                FULL_THROTTLE_CALL + SESSION_CALL,
                1,
            )
        elif GLOBAL_VALIDATION_ANCHOR in text:
            text = text.replace(
                GLOBAL_VALIDATION_ANCHOR,
                SESSION_CALL + GLOBAL_VALIDATION_ANCHOR,
                1,
            )
        else:
            raise SystemExit(
                "No encontré el hook session/global esperado."
            )

    if text.count(IMPORT_LINE) != 1:
        raise SystemExit(
            "ERROR: import de throttle modulation recurrence duplicado."
        )

    if text.count(
        "enrich_analysis_with_throttle_modulation_recurrence("
    ) != 1:
        raise SystemExit(
            "ERROR: hook de throttle modulation recurrence duplicado/ausente."
        )

    compile(text, str(target), "exec")

    if text == original:
        print(
            "Throttle Modulation Recurrence v1.0 ya estaba instalado."
        )
        return 0

    backup = target.with_suffix(
        target.suffix
        + ".pre_throttle_modulation_recurrence_v1_0.bak"
    )

    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")

    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print("Throttle Modulation Recurrence v1.0: ACTIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
