from pathlib import Path
import shutil
import sys


PATCHER_VERSION = "1.0.0"

IMPORT_LINE = (
    "from throttle_coaching_evidence_gate_v1_0 import "
    "enrich_analysis_with_throttle_coaching_evidence_gate\n"
)

PROFILE_CALL = """        # Perfil unificado por punto físico de acelerador.
        # Sólo reúne hechos ya detectados; no modifica decisiones.
        enrich_analysis_with_throttle_physical_point_profiles(
            analysis_output,
        )

"""

GATE_CALL = """        # Gate de evidencia para coaching de acelerador.
        # Shadow mode: no modifica ranking, prioridad ni coaching activo.
        enrich_analysis_with_throttle_coaching_evidence_gate(
            analysis_output,
        )

"""

IMPORT_ANCHORS = (
    "from throttle_physical_point_profile_v1_0 import "
    "enrich_analysis_with_throttle_physical_point_profiles\n",
    "from sector_analysis import SectorAnalysis\n",
)

GLOBAL_VALIDATION_ANCHOR = """        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
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
            raise SystemExit("No encontré ancla de import compatible.")

    if GATE_CALL not in text:
        if PROFILE_CALL in text:
            text = text.replace(PROFILE_CALL, PROFILE_CALL + GATE_CALL, 1)
        elif GLOBAL_VALIDATION_ANCHOR in text:
            text = text.replace(
                GLOBAL_VALIDATION_ANCHOR,
                GATE_CALL + GLOBAL_VALIDATION_ANCHOR,
                1,
            )
        else:
            raise SystemExit("No encontré el hook session/global esperado.")

    if text.count(IMPORT_LINE) != 1:
        raise SystemExit("ERROR: import del coaching evidence gate duplicado.")

    if text.count("enrich_analysis_with_throttle_coaching_evidence_gate(") != 1:
        raise SystemExit("ERROR: hook del coaching evidence gate duplicado/ausente.")

    compile(text, str(target), "exec")

    if text == original:
        print("Throttle Coaching Evidence Gate v1.0 ya estaba instalado.")
        return 0

    backup = target.with_suffix(
        target.suffix + ".pre_throttle_coaching_evidence_gate_v1_0.bak"
    )
    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")
    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print("Throttle Coaching Evidence Gate v1.0: ACTIVE / SHADOW MODE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
