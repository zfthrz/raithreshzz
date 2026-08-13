from pathlib import Path
import shutil
import sys


PATCHER_VERSION = "1.0.0"

IMPORT_LINE = (
    "from throttle_sustained_modulation_v1_0 import "
    "enrich_objective_with_sustained_throttle_modulations\n"
)

IMPORT_ANCHORS = (
    "from throttle_episode_sequence_v1_0 import "
    "enrich_objective_with_throttle_event_sequences\n",
    "from throttle_point_v1_2_1 import enrich_objective_with_throttle_points\n",
    "from braking_point_v2_1 import enrich_objective_with_braking_points\n",
    "from sector_analysis import SectorAnalysis\n",
)

CALL_SIGNATURE = (
    "enrich_objective_with_sustained_throttle_modulations(\n"
    "                comparison,\n"
    "                objective_analysis,\n"
    "            )"
)

SEQUENCE_CALL = """            enrich_objective_with_throttle_event_sequences(
                comparison,
                objective_analysis,
            )
"""

THROTTLE_CALL = """            enrich_objective_with_throttle_points(
                comparison,
                objective_analysis,
            )
"""


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
                text = text.replace(anchor, anchor + IMPORT_LINE, 1)
                inserted = True
                break

        if not inserted:
            raise SystemExit("No encontré un ancla de import compatible.")

    if CALL_SIGNATURE not in text:
        insert = """
            # Modulación sostenida de acelerador.
            # Observacional: no modifica ranking ni coaching.
            enrich_objective_with_sustained_throttle_modulations(
                comparison,
                objective_analysis,
            )
"""

        if SEQUENCE_CALL in text:
            text = text.replace(
                SEQUENCE_CALL,
                SEQUENCE_CALL + insert,
                1,
            )
        elif THROTTLE_CALL in text:
            text = text.replace(
                THROTTLE_CALL,
                THROTTLE_CALL + insert,
                1,
            )
        else:
            raise SystemExit(
                "No encontré hook de throttle/sequence compatible."
            )

    if text.count(IMPORT_LINE) != 1:
        raise SystemExit(
            "ERROR: import de sustained modulation duplicado."
        )

    if CALL_SIGNATURE not in text:
        raise SystemExit(
            "ERROR: hook de sustained modulation ausente."
        )

    compile(text, str(target), "exec")

    if text == original:
        print("Throttle Sustained Modulation v1.0 ya estaba instalado.")
        return 0

    backup = target.with_suffix(
        target.suffix + ".pre_throttle_sustained_modulation_v1_0.bak"
    )

    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")

    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print("Throttle Sustained Modulation v1.0: ACTIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
