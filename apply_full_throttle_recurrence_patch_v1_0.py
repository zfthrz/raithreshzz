from pathlib import Path
import re
import shutil
import sys


PATCHER_VERSION = "1.0.0"

IMPORT_LINE = (
    "from full_throttle_recurrence_v1_0 import "
    "enrich_analysis_with_full_throttle_attainment_recurrence\n"
)

IMPORT_ANCHOR = "from sector_analysis import SectorAnalysis\n"

SESSION_HOOK = """        # Recurrencia de full-throttle attainment entre vueltas.
        # Observacional: no modifica ranking, prioridad ni coaching.
        enrich_analysis_with_full_throttle_attainment_recurrence(
            analysis_output,
        )

"""

GLOBAL_VALIDATION_ANCHOR = """        # ====================================================
        # VALIDACIÓN GLOBAL
        # ====================================================
"""


def _remove_old_imports(text):
    return re.sub(
        r"^from\s+full_throttle_recurrence[^\s]*\s+import\s+"
        r"enrich_analysis_with_full_throttle_attainment_recurrence\s*$\n?",
        "",
        text,
        flags=re.MULTILINE,
    )


def _remove_old_hook(text):
    text = text.replace(SESSION_HOOK, "")
    pattern = re.compile(
        r"\n(?P<indent>[ \t]*)"
        r"enrich_analysis_with_full_throttle_attainment_recurrence\(\n"
        r"(?P=indent)[ \t]+analysis_output,\n"
        r"(?P=indent)\)\n"
    )
    return pattern.sub("\n", text)


def patch_text(original):
    text = _remove_old_imports(original)

    if IMPORT_ANCHOR not in text:
        raise ValueError("No encontré el import anchor de SectorAnalysis.")

    text = text.replace(
        IMPORT_ANCHOR,
        IMPORT_ANCHOR + IMPORT_LINE,
        1,
    )

    text = _remove_old_hook(text)

    if GLOBAL_VALIDATION_ANCHOR not in text:
        raise ValueError("No encontré el bloque VALIDACIÓN GLOBAL.")

    text = text.replace(
        GLOBAL_VALIDATION_ANCHOR,
        SESSION_HOOK + GLOBAL_VALIDATION_ANCHOR,
        1,
    )

    compile(text, "<patched_analyze_telemetry>", "exec")
    return text


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "analyze_telemetry.py")
    if not target.is_file():
        raise SystemExit(f"No existe: {target}")

    original = target.read_text(encoding="utf-8")
    try:
        text = patch_text(original)
    except ValueError as exc:
        raise SystemExit(str(exc))

    if text == original:
        print("Full Throttle Recurrence v1.0 ya estaba instalado.")
        return 0

    backup = target.with_suffix(
        target.suffix + ".pre_full_throttle_recurrence_v1_0.bak"
    )
    if not backup.exists():
        shutil.copy2(target, backup)

    target.write_text(text, encoding="utf-8")
    print(f"Parche v{PATCHER_VERSION} aplicado: {target}")
    print(f"Backup: {backup}")
    print("Full Throttle Attainment Recurrence: 1.0 / observational")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
