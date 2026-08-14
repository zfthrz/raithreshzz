from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SESSION_DIR = ROOT / "data" / "reference_sessions"
REFERENCE_SESSION_RE = re.compile(
    r".+_[A-Za-z]+_\d{4}-\d{2}-\d{2}T\d{2}_\d{2}_\d{2}Z(?:\(1\))?\.json$"
)

RUNTIME_PATHSPECS = (
    ":(glob)*_llm/**",
    ":(glob)*_llm_analysis*.json",
    "race_engineer_history.duckdb",
    "race_engineer_history_backup.duckdb",
    ":(glob)*.pre_objective_python_recovery.bak",
)

# Releases históricos que ya no deben vivir en la raíz operativa.
# Se conservan bajo legacy/; no se borran.
SUPERSEDED_RELEASES = {
    "legacy/llm": (
        "llm_analysis_v3_8_17.py",
        "llm_analysis_v3_10_0_deepseek_v2.py",
        "llm_analysis_v3_10_8_4_deepseek_v2.py",
        "llm_analysis_v3_10_8_4_ingenierov3.py",
        "llm_analysis_v3_10_8_5_1_deepseek_v2.py",
        "llm_analysis_v3_10_8_5_1_ingenierov3.py",
        "llm_analysis_v3_10_8_5_3_deepseek_v2.py",
        "llm_analysis_v3_10_8_5_3_ingenierov3.py",
        "llm_analysis_v3_10_8_5_4_deepseek_v2_filenamefix.py",
    ),
    "legacy/tools": (
        "audit_dual_reference_context_v0_1.py",
        "audit_episode_pair_matches_v0_1.py",
        "audit_historical_reference_v0_1.py",
        "build_dual_reference_context_v0_1.py",
        "deepseek_pair_reviewer_v1_0.py",
        "deepseek_pair_reviewer_v1_1.py",
        "episode_pair_matcher_v0_1.py",
        "episode_pair_matcher_v0_2.py",
        "prepare_calibration_batch_v1_2.py",
        "prepare_deepseek_ambiguous_pool_v1_0.py",
        "select_historical_reference_v0_1.py",
        "validate_dual_reference_context_v0_1.py",
        "validate_episode_pair_matcher_v0_1.py",
        "validate_episode_pair_matcher_v0_2.py",
        "validate_historical_reference_v0_1.py",
    ),
    "legacy/docs": (
        "MISSING_CORE_MODULES.md",
    ),
}


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def tracked_runtime_files() -> list[str]:
    result = git("ls-files", "-z", "--", *RUNTIME_PATHSPECS)
    return sorted(item for item in result.stdout.split("\0") if item)


def root_reference_sessions() -> list[Path]:
    return sorted(
        path
        for path in ROOT.glob("*.json")
        if REFERENCE_SESSION_RE.fullmatch(path.name)
    )


def is_tracked(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    result = git("ls-files", "--error-unmatch", "--", relative, check=False)
    return result.returncode == 0


def existing_reference_copy(source: Path) -> Path | None:
    """Find an identical canonical/reference copy already stored under data/."""
    data_root = ROOT / "data"
    if not data_root.is_dir():
        return None
    excluded_roots = {
        REFERENCE_SESSION_DIR.resolve(),
        (data_root / "generated").resolve(),
        (data_root / "raw").resolve(),
        (data_root / "local").resolve(),
    }
    for candidate in data_root.rglob(source.name):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if any(root == resolved or root in resolved.parents for root in excluded_roots):
            continue
        if candidate.stat().st_size != source.stat().st_size:
            continue
        if candidate.read_bytes() == source.read_bytes():
            return candidate
    return None


def remove_tracked_or_local(path: Path) -> None:
    relative = path.relative_to(ROOT).as_posix()
    if is_tracked(path):
        result = git("rm", "--", relative, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
    else:
        path.unlink()


def move_reference_sessions() -> list[tuple[str, str]]:
    moved: list[tuple[str, str]] = []
    REFERENCE_SESSION_DIR.mkdir(parents=True, exist_ok=True)

    for source in root_reference_sessions():
        source_rel = source.relative_to(ROOT).as_posix()

        canonical = existing_reference_copy(source)
        if canonical is not None:
            canonical_rel = canonical.relative_to(ROOT).as_posix()
            remove_tracked_or_local(source)
            moved.append((source_rel, f"DEDUP -> {canonical_rel}"))
            continue

        destination = REFERENCE_SESSION_DIR / source.name
        if destination.exists():
            if source.read_bytes() != destination.read_bytes():
                raise FileExistsError(
                    f"No se puede mover {source.name}: ya existe {destination} y difiere."
                )
            remove_tracked_or_local(source)
            moved.append((source_rel, f"DEDUP -> {destination.relative_to(ROOT).as_posix()}"))
            continue

        dest_rel = destination.relative_to(ROOT).as_posix()
        if is_tracked(source):
            result = git("mv", "--", source_rel, dest_rel, check=False)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout)
        else:
            shutil.move(str(source), str(destination))
        moved.append((source_rel, dest_rel))

    return moved


def apply_index_cleanup() -> None:
    result = git(
        "rm",
        "-r",
        "--cached",
        "--ignore-unmatch",
        "--",
        *RUNTIME_PATHSPECS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def root_runtime_artifacts() -> list[Path]:
    rows: list[Path] = []
    rows.extend(sorted(path for path in ROOT.glob("*_llm") if path.is_dir()))
    rows.extend(sorted(path for path in ROOT.glob("*_llm_analysis*.json") if path.is_file()))
    rows.extend(sorted(path for path in ROOT.glob("*.pre_objective_python_recovery.bak") if path.is_file()))
    main_db = ROOT / "race_engineer_history.duckdb"
    if main_db.is_file():
        rows.append(main_db)
    backup_db = ROOT / "race_engineer_history_backup.duckdb"
    if backup_db.is_file():
        rows.append(backup_db)
    return rows


def archive_runtime_artifacts() -> list[tuple[str, str]]:
    archive_root = ROOT / "data" / "local" / "legacy_runtime"
    moved: list[tuple[str, str]] = []
    for source in root_runtime_artifacts():
        bucket = "llm_runs" if source.is_dir() and source.name.endswith("_llm") else "misc"
        if source.is_file() and "_llm_analysis" in source.name:
            bucket = "llm_results"
        elif source.name.endswith(".bak"):
            bucket = "backups"
        elif source.name == "race_engineer_history_backup.duckdb":
            bucket = "backups"
        if source.name == "race_engineer_history.duckdb":
            destination = ROOT / "data" / "local" / source.name
        else:
            destination = archive_root / bucket / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(
                f"No se puede archivar {source.name}: ya existe {destination}."
            )
        shutil.move(str(source), str(destination))
        moved.append((source.relative_to(ROOT).as_posix(), destination.relative_to(ROOT).as_posix()))
    return moved


def superseded_root_releases() -> list[tuple[Path, Path]]:
    rows: list[tuple[Path, Path]] = []
    for destination_dir, names in SUPERSEDED_RELEASES.items():
        for name in names:
            source = ROOT / name
            if source.is_file():
                rows.append((source, ROOT / destination_dir / name))
    return rows


def move_superseded_releases() -> list[tuple[str, str]]:
    moved: list[tuple[str, str]] = []
    for source, destination in superseded_root_releases():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if source.read_bytes() != destination.read_bytes():
                raise FileExistsError(
                    f"No se puede archivar {source.name}: {destination} ya existe y difiere."
                )
            # Caso de migración reanudada: el destino ya contiene la misma release.
            source.unlink()
            continue

        source_rel = source.relative_to(ROOT).as_posix()
        dest_rel = destination.relative_to(ROOT).as_posix()
        if is_tracked(source):
            result = git("mv", "--", source_rel, dest_rel, check=False)
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout)
        else:
            shutil.move(str(source), str(destination))
        moved.append((source_rel, dest_rel))
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audita/ordena artefactos de Race Engineer. La limpieza de índice "
            "no borra archivos runtime locales."
        )
    )
    parser.add_argument(
        "--apply-index-cleanup",
        action="store_true",
        help="Dejar de trackear *_llm, LLM outputs, DB locales y backups runtime.",
    )
    parser.add_argument(
        "--apply-layout-cleanup",
        action="store_true",
        help="Mover JSON deterministas de sesión desde la raíz a data/reference_sessions/.",
    )
    parser.add_argument(
        "--apply-source-cleanup",
        action="store_true",
        help="Archivar releases/docs superseded de la raíz bajo legacy/ sin borrarlos.",
    )
    parser.add_argument(
        "--archive-runtime",
        action="store_true",
        help="Mover *_llm y outputs runtime históricos a data/local/legacy_runtime/.",
    )
    parser.add_argument(
        "--apply-all",
        action="store_true",
        help="Aplicar layout + source + index cleanup y archivar runtime histórico.",
    )
    args = parser.parse_args()

    inside = git("rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        print("REPO HYGIENE: no se encontró un checkout Git.")
        return 2

    tracked = tracked_runtime_files()
    references = root_reference_sessions()
    superseded = superseded_root_releases()
    runtime_on_disk = root_runtime_artifacts()

    print("=" * 72)
    print("RACE ENGINEER - REPO HYGIENE")
    print("=" * 72)
    print(f"Runtime artifacts todavía trackeados: {len(tracked)}")
    print(f"JSON deterministas todavía en la raíz: {len(references)}")
    print(f"Releases superseded todavía en la raíz: {len(superseded)}")
    print(f"Runtime histórico todavía físicamente en la raíz: {len(runtime_on_disk)}")

    for item in tracked[:20]:
        print(f"  [runtime] {item}")
    if len(tracked) > 20:
        print(f"  ... y {len(tracked) - 20} runtime artifact(s) más")

    for path in references[:20]:
        print(f"  [layout]  {path.name}")
    for source, destination in superseded[:20]:
        print(
            f"  [legacy]  {source.name} -> "
            f"{destination.relative_to(ROOT).as_posix()}"
        )

    apply_layout = args.apply_layout_cleanup or args.apply_all
    apply_source = args.apply_source_cleanup or args.apply_all
    apply_index = args.apply_index_cleanup or args.apply_all
    apply_archive = args.archive_runtime or args.apply_all

    if apply_layout and references:
        moved = move_reference_sessions()
        print()
        print(f"Reference session JSON movidos: {len(moved)}")
        for source, destination in moved:
            print(f"  {source} -> {destination}")

    if apply_source and superseded:
        moved = move_superseded_releases()
        print()
        print(f"Releases superseded archivadas: {len(moved)}")
        for source, destination in moved:
            print(f"  {source} -> {destination}")

    if apply_index and tracked:
        apply_index_cleanup()
        print()
        print("Runtime artifacts removidos del índice Git; se conservan en el disco.")

    if apply_archive and runtime_on_disk:
        moved = archive_runtime_artifacts()
        print()
        print(f"Runtime histórico archivado fuera de la raíz: {len(moved)}")
        for source, destination in moved[:20]:
            print(f"  {source} -> {destination}")
        if len(moved) > 20:
            print(f"  ... y {len(moved) - 20} artifact(s) más")

    remaining_runtime = tracked_runtime_files()
    remaining_references = root_reference_sessions()
    remaining_superseded = superseded_root_releases()
    remaining_runtime_on_disk = root_runtime_artifacts()

    print()
    print(f"Runtime artifacts trackeados restantes: {len(remaining_runtime)}")
    print(f"JSON deterministas en raíz restantes: {len(remaining_references)}")
    print(f"Releases superseded en raíz restantes: {len(remaining_superseded)}")
    print(f"Runtime histórico físico en raíz restante: {len(remaining_runtime_on_disk)}")

    if (
        not remaining_runtime
        and not remaining_references
        and not remaining_superseded
        and not remaining_runtime_on_disk
    ):
        print("RESULT: CLEAN")
        return 0

    if not (apply_layout or apply_source or apply_index or apply_archive):
        print()
        print("Limpieza recomendada:")
        print("  python scripts/repo_hygiene.py --apply-all")
    else:
        if remaining_references and not apply_layout:
            print("Falta aplicar --apply-layout-cleanup.")
        if remaining_superseded and not apply_source:
            print("Falta aplicar --apply-source-cleanup.")
        if remaining_runtime and not apply_index:
            print("Falta aplicar --apply-index-cleanup.")
        if remaining_runtime_on_disk and not apply_archive:
            print("Falta aplicar --archive-runtime.")

    print("RESULT: ACTION_REQUIRED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
