from pathlib import Path
import shutil
import sys


PATCHER_VERSION = "2.1.0"

NEW_IMPORT_LINE = (
    "from braking_point_v2_1 import enrich_objective_with_braking_points\n"
)

LEGACY_IMPORT_LINES = (
    "from braking_point import enrich_objective_with_braking_points\n",
    "from braking_point_v1 import enrich_objective_with_braking_points\n",
    "from braking_point_v1_0 import enrich_objective_with_braking_points\n",
    "from braking_point_v1_1 import enrich_objective_with_braking_points\n",
    "from braking_point_v2_0 import enrich_objective_with_braking_points\n",
)

IMPORT_ANCHOR = "from sector_analysis import SectorAnalysis\n"

CALL_ANCHOR = """            objective_analysis = build_objective_analysis(
                zones,
                real_delta,
                comparison,
            )
"""

CALL_INSERT = CALL_ANCHOR + """
            # Punto de frenada determinista (braking_point_v2_1.py).
            # Sólo enriquece los episodios; no modifica ranking ni deltas.
            enrich_objective_with_braking_points(
                comparison,
                objective_analysis,
            )
"""


def main():
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "analyze_telemetry.py"
    )

    if not target.is_file():
        raise SystemExit(f"No existe: {target}")

    original = target.read_text(encoding="utf-8")
    text = original

    # 1) Migrar imports legacy al módulo versionado v2.1.
    for legacy_import in LEGACY_IMPORT_LINES:
        text = text.replace(legacy_import, "")

    # Si por una corrida anterior quedó duplicado el import nuevo,
    # dejar exactamente una sola copia.
    while text.count(NEW_IMPORT_LINE) > 1:
        text = text.replace(NEW_IMPORT_LINE, "", 1)

    if NEW_IMPORT_LINE not in text:
        if IMPORT_ANCHOR not in text:
            raise SystemExit(
                "No encontré el ancla de imports esperada. "
                "No se modificó el archivo."
            )
        text = text.replace(
            IMPORT_ANCHOR,
            IMPORT_ANCHOR + NEW_IMPORT_LINE,
            1,
        )

    # 2) Migrar comentarios viejos del hook.
    legacy_comments = (
        "# Punto de frenada determinista v1.",
        "# Punto de frenada determinista v1.1.",
        "# Punto de frenada determinista (versión provista por braking_point.py).",
        "# Punto de frenada determinista (versión provista por braking_point_v2_0.py).",
        "# Punto de frenada determinista (braking_point_v2_0.py).",
    )
    current_comment = (
        "# Punto de frenada determinista (braking_point_v2_1.py)."
    )
    for legacy in legacy_comments:
        text = text.replace(legacy, current_comment)

    # 3) Insertar el hook sólo si todavía no existe.
    call_signature = (
        "enrich_objective_with_braking_points(\n"
        "                comparison,\n"
        "                objective_analysis,\n"
        "            )"
    )

    if call_signature not in text:
        if CALL_ANCHOR not in text:
            raise SystemExit(
                "No encontré el bloque build_objective_analysis esperado. "
                "No se modificó el archivo."
            )
        text = text.replace(
            CALL_ANCHOR,
            CALL_INSERT,
            1,
        )

    # 4) Validaciones del texto final.
    for legacy_import in LEGACY_IMPORT_LINES:
        if legacy_import in text:
            raise SystemExit(
                "ERROR: quedó un import legacy de braking_point."
            )

    if text.count(NEW_IMPORT_LINE) != 1:
        raise SystemExit(
            "ERROR: el import braking_point_v2_1 no quedó exactamente una vez."
        )

    if call_signature not in text:
        raise SystemExit(
            "ERROR: no quedó instalado el hook de braking point."
        )

    if text == original:
        print(
            f"El parche v{PATCHER_VERSION} ya estaba aplicado correctamente."
        )
        return 0

    backup = target.with_suffix(
        target.suffix + ".pre_braking_point_v2_1.bak"
    )
    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")

    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print("Import activo:")
    print("  from braking_point_v2_1 import enrich_objective_with_braking_points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
