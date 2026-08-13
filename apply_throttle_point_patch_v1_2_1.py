from pathlib import Path
import shutil
import sys


PATCHER_VERSION = "1.2.1"

TARGET_IMPORT = (
    "from throttle_point_v1_2_1 import enrich_objective_with_throttle_points\n"
)

OLD_IMPORTS = (
    "from throttle_point_v1_0 import enrich_objective_with_throttle_points\n",
    "from throttle_point_v1_1 import enrich_objective_with_throttle_points\n",
    "from throttle_point_v1_2 import enrich_objective_with_throttle_points\n",
)

IMPORT_ANCHORS = (
    "from braking_point_v2_1 import enrich_objective_with_braking_points\n",
    "from sector_analysis import SectorAnalysis\n",
)


def main():
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "analyze_telemetry.py"
    )

    if not target.is_file():
        raise SystemExit(f"No existe: {target}")

    original = target.read_text(encoding="utf-8")
    text = original

    for old in OLD_IMPORTS:
        text = text.replace(old, "")

    while text.count(TARGET_IMPORT) > 1:
        text = text.replace(TARGET_IMPORT, "", 1)

    if TARGET_IMPORT not in text:
        inserted = False
        for anchor in IMPORT_ANCHORS:
            if anchor in text:
                text = text.replace(anchor, anchor + TARGET_IMPORT, 1)
                inserted = True
                break

        if not inserted:
            raise SystemExit(
                "No encontré ancla de imports compatible. No se modificó."
            )

    call_signature = (
        "enrich_objective_with_throttle_points(\n"
        "                comparison,\n"
        "                objective_analysis,\n"
        "            )"
    )

    if call_signature not in text:
        raise SystemExit(
            "No encontré el hook throttle ya instalado. "
            "Aplicá primero el patch v1.2 o revisá analyze_telemetry.py."
        )

    if text.count(TARGET_IMPORT) != 1:
        raise SystemExit(
            "ERROR: el import throttle_point_v1_2_1 no quedó exactamente una vez."
        )

    backup = target.with_suffix(
        target.suffix + ".pre_throttle_point_v1_2_1.bak"
    )
    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")

    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print(
        "Import activo: from throttle_point_v1_2_1 import "
        "enrich_objective_with_throttle_points"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
