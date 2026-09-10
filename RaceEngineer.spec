# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

root = Path(SPECPATH).resolve()
python_root = Path(sys.base_prefix).resolve()
worker_modules = [
    "analyze_telemetry",
    "build_cross_session_comparison",
    "build_dual_reference_context",
    "build_historical_coaching_candidates",
    "build_historical_telemetry_evidence",
    "deterministic_debrief",
    "render_historical_debrief",
    "select_historical_reference",
    "select_session_persistent_patterns",
    "session_history",
    "validate_cross_session_comparison",
    "validate_historical_debrief",
    "validate_historical_telemetry_evidence",
    "validate_llm_analysis_output",
]
common_datas = [
    (str(root / "track_profiles"), "track_profiles"),
    (str(root / "RELEASE_VERSION.txt"), "."),
    (str(root / "docs" / "RELEASE_NOTES_V0_1_0.md"), "."),
    (str(root / "LICENSE.txt"), "."),
    (str(root / "THIRD_PARTY_NOTICES.md"), "."),
    (str(root / "PUBLIC_INSTALLATION.md"), "."),
    (str(python_root / "LICENSE.txt"), "third_party_licenses/Python-3.12.10"),
    (
        str(python_root / "Lib" / "site-packages" / "numpy-2.5.2.dist-info" / "licenses"),
        "third_party_licenses/numpy-2.5.2",
    ),
    (
        str(python_root / "Lib" / "site-packages" / "pandas-3.0.5.dist-info" / "LICENSE"),
        "third_party_licenses/pandas-3.0.5",
    ),
    (
        str(python_root / "Lib" / "site-packages" / "duckdb-1.5.5.dist-info" / "licenses"),
        "third_party_licenses/duckdb-1.5.5",
    ),
    (
        str(python_root / "Lib" / "site-packages" / "python_dateutil-2.9.0.post0.dist-info" / "LICENSE"),
        "third_party_licenses/python-dateutil-2.9.0.post0",
    ),
    (
        str(python_root / "Lib" / "site-packages" / "tzdata-2026.3.dist-info" / "licenses"),
        "third_party_licenses/tzdata-2026.3",
    ),
    (
        str(python_root / "Lib" / "site-packages" / "six-1.17.0.dist-info" / "LICENSE"),
        "third_party_licenses/six-1.17.0",
    ),
]
tk_datas = [
    (str(python_root / "tcl" / "tcl8.6"), "_tcl_data"),
    (str(python_root / "tcl" / "tk8.6"), "_tk_data"),
]
tk_binaries = [
    (str(python_root / "DLLs" / "_tkinter.pyd"), "."),
    (str(python_root / "DLLs" / "tcl86t.dll"), "."),
    (str(python_root / "DLLs" / "tk86t.dll"), "."),
    (str(python_root / "DLLs" / "zlib1.dll"), "."),
]


def analysis(script, *, hiddenimports=None, datas=None, binaries=None, runtime_hooks=None):
    return Analysis(
        [str(root / script)],
        pathex=[str(root)],
        binaries=binaries or [],
        datas=datas or [],
        hiddenimports=hiddenimports or [],
        hookspath=[str(root / "packaging_hooks")],
        hooksconfig={},
        runtime_hooks=runtime_hooks or [],
        excludes=[
            "llm_analysis",
            "llm_analysis_deepseek",
            "llm_analysis_llamacpp",
            "openai",
        ],
        noarchive=False,
        optimize=0,
    )


def executable(name, item, *, console):
    archive = PYZ(item.pure)
    return EXE(
        archive,
        item.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        contents_directory=".",
    )


gui_analysis = analysis(
    "RaceEngineerPublic.pyw",
    hiddenimports=["tkinter", "tkinter.ttk"],
    datas=common_datas + tk_datas,
    binaries=tk_binaries,
    runtime_hooks=[str(root / "packaging_runtime_tk.py")],
)
analyzer_analysis = analysis("RaceEngineerAnalyze.py")
cli_analysis = analysis("RaceEngineerCLI.py", hiddenimports=["uuid"])
worker_analysis = analysis("RaceEngineerWorker.py", hiddenimports=worker_modules)

gui = executable("RaceEngineer", gui_analysis, console=False)
analyzer = executable("RaceEngineerAnalyze", analyzer_analysis, console=True)
cli = executable("RaceEngineerCLI", cli_analysis, console=True)
worker = executable("RaceEngineerWorker", worker_analysis, console=True)

coll = COLLECT(
    gui,
    analyzer,
    cli,
    worker,
    gui_analysis.binaries,
    gui_analysis.datas,
    analyzer_analysis.binaries,
    analyzer_analysis.datas,
    cli_analysis.binaries,
    cli_analysis.datas,
    worker_analysis.binaries,
    worker_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RaceEngineer",
)
