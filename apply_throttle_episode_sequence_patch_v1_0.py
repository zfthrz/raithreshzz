from pathlib import Path
import shutil
import sys


PATCHER_VERSION = "1.0.0"

IMPORT_LINE = (
    "from throttle_episode_sequence_v1_0 import "
    "enrich_objective_with_throttle_event_sequences\n"
)

IMPORT_ANCHORS = (
    "from throttle_point_v1_2_1 import enrich_objective_with_throttle_points\n",
    "from braking_point_v2_1 import enrich_objective_with_braking_points\n",
    "from sector_analysis import SectorAnalysis\n",
)

CALL_SIGNATURE = (
    "enrich_objective_with_throttle_event_sequences(\n"
    "                comparison,\n"
    "                objective_analysis,\n"
    "            )"
)

THROTTLE_CALL = """            enrich_objective_with_throttle_points(
                comparison,
                objective_analysis,
            )
"""

BUILD_CALL = """            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
"""


def main():
    target = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "analyze_telemetry.py"
    )

    if not target.is_file():
        raise SystemExit(
            f"No existe: {target}"
        )

    original = target.read_text(
        encoding="utf-8"
    )
    text = original

    while text.count(IMPORT_LINE) > 1:
        text = text.replace(
            IMPORT_LINE,
            "",
            1,
        )

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
                "No encontré un ancla de import compatible."
            )

    if CALL_SIGNATURE not in text:
        insert = """
            # Secuencia física de eventos de acelerador por episodio.
            # Observacional: no modifica ranking ni coaching.
            enrich_objective_with_throttle_event_sequences(
                comparison,
                objective_analysis,
            )
"""

        if THROTTLE_CALL in text:
            text = text.replace(
                THROTTLE_CALL,
                THROTTLE_CALL + insert,
                1,
            )
        elif BUILD_CALL in text:
            text = text.replace(
                BUILD_CALL,
                BUILD_CALL + insert,
                1,
            )
        else:
            raise SystemExit(
                "No encontré hook de throttle ni build_objective_analysis."
            )

    if text.count(IMPORT_LINE) != 1:
        raise SystemExit(
            "ERROR: import de throttle_episode_sequence duplicado."
        )

    if CALL_SIGNATURE not in text:
        raise SystemExit(
            "ERROR: hook de throttle_event_sequence ausente."
        )

    compile(
        text,
        str(target),
        "exec",
    )

    if text == original:
        print(
            "Throttle Episode Sequence v1.0 ya estaba instalado."
        )
        return 0

    backup = target.with_suffix(
        target.suffix
        + ".pre_throttle_episode_sequence_v1_0.bak"
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
        f"Parche v{PATCHER_VERSION} aplicado: {target}"
    )
    print(
        f"Backup: {backup}"
    )
    print(
        "Throttle Episode Sequence v1.0: ACTIVE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
