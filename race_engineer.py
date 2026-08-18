from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from runtime_paths import (
    PROJECT_ROOT,
    analysis_output_path,
    cross_session_output_path,
    dual_reference_output_path,
    h5_3_candidates_path,
    h5_3_section_path,
    historical_llm_debug_dir,
    historical_llm_output_path,
    historical_reference_output_path,
    history_db_default_path,
    llm_result_dir,
    run_state_path,
)
from cross_session_context import (
    CrossSessionNotApplicableError,
    resolve_cross_session_pair,
)


ORCHESTRATOR_VERSION = "0.3"
LLM_ANALYSIS_VERSION_FILE = "3_10_8_5_4"

STATUS_RUN = "RUN"
STATUS_REUSED = "REUSED"
STATUS_SKIPPED = "SKIPPED_NOT_APPLICABLE"
STATUS_FAILED = "FAILED"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stat_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def script_signature(path: Path) -> dict[str, str]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "stages": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "stages": {},
        }
    if not isinstance(payload, dict):
        return {
            "orchestrator_version": ORCHESTRATOR_VERSION,
            "stages": {},
        }
    payload.setdefault("stages", {})
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["orchestrator_version"] = ORCHESTRATOR_VERSION
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def stage_is_reusable(
    state: dict[str, Any],
    name: str,
    signature: dict[str, Any],
    *,
    required_paths: tuple[Path, ...] = (),
) -> bool:
    stage = (state.get("stages") or {}).get(name)
    if not isinstance(stage, dict):
        return False
    if stage.get("signature") != signature:
        return False
    return all(path.exists() for path in required_paths)


def record_stage(
    state: dict[str, Any],
    name: str,
    *,
    signature: dict[str, Any],
    status: str,
    output: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "status": status,
        "signature": signature,
    }
    if output is not None:
        payload["output"] = output
    if details:
        payload["details"] = details
    state.setdefault("stages", {})[name] = payload


def run_checked(args: list[str]) -> None:
    print()
    print("+ " + " ".join(_quote_for_display(x) for x in args))
    subprocess.run(args, cwd=PROJECT_ROOT, check=True)


def _quote_for_display(value: str) -> str:
    if not value or any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def resolve_database(argument: str) -> Path:
    path = Path(argument).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".duckdb":
        raise ValueError("El input de analyze debe ser un archivo .duckdb.")
    return path


def history_db_path(argument: str | None) -> Path:
    if argument:
        path = Path(argument).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()
    return history_db_default_path().resolve()


def llm_script(backend: str) -> Path:
    if backend == "deepseek":
        return PROJECT_ROOT / "llm_analysis_deepseek.py"
    if backend == "ollama":
        return PROJECT_ROOT / "llm_analysis.py"
    raise ValueError(f"Backend no soportado: {backend}")


def llm_model_name(backend: str) -> str:
    if backend == "deepseek":
        return os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    return "ingenierov3"


def llm_output_path(analysis_json: Path, backend: str) -> Path:
    stem = analysis_json.stem
    model = llm_model_name(backend)
    if backend == "deepseek":
        filename = (
            f"{stem}_llm_analysis_v{LLM_ANALYSIS_VERSION_FILE}"
            f"_deepseek_v2_{model}.json"
        )
    else:
        filename = (
            f"{stem}_llm_analysis_v{LLM_ANALYSIS_VERSION_FILE}_{model}.json"
        )
    return llm_result_dir(analysis_json) / filename


def import_history(analysis_json: Path, db_path: Path) -> dict[str, Any]:
    import duckdb
    import session_history

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path))
    try:
        session_history.initialize_schema(connection)
        return session_history.import_analysis_json(connection, str(analysis_json))
    finally:
        connection.close()


def h4_applicability(db_path: Path, session_id: int) -> tuple[bool, list[str]]:
    import duckdb
    import select_historical_reference

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        select_historical_reference.require_schema4(connection)
        target = select_historical_reference.load_session(connection, session_id)
        reference_lap = select_historical_reference.safe_int(target.get("reference_lap"))
        lap = select_historical_reference.load_reference_lap(
            connection,
            session_id,
            reference_lap,
        )
        errors = select_historical_reference.target_gate_errors(
            target,
            lap,
            select_historical_reference.DEFAULT_MIN_VALID_LAPS,
        )
        return not errors, list(errors)
    finally:
        connection.close()


def print_stage(name: str, status: str, detail: str | None = None) -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[{name}] {status}{suffix}")


def analyze_command(args: argparse.Namespace) -> int:
    database = resolve_database(args.database)
    state_path = run_state_path(database)
    state = load_state(state_path)
    state["database"] = str(database)

    analyzer = PROJECT_ROOT / "analyze_telemetry.py"
    validator = PROJECT_ROOT / "validate_llm_analysis_output.py"
    history_script = PROJECT_ROOT / "session_history.py"
    h4_script = PROJECT_ROOT / "select_historical_reference.py"
    h5_script = PROJECT_ROOT / "build_dual_reference_context.py"
    h5_2_script = PROJECT_ROOT / "build_cross_session_comparison.py"
    h5_2_validator = PROJECT_ROOT / "validate_cross_session_comparison.py"
    h5_2_llm_script = PROJECT_ROOT / "historical_llm_analysis.py"
    h5_2_llm_validator = PROJECT_ROOT / "validate_historical_llm_analysis.py"
    h5_3_candidate_script = PROJECT_ROOT / "build_historical_coaching_candidates.py"
    h5_3_render_script = PROJECT_ROOT / "render_historical_debrief.py"
    h5_3_validator_script = PROJECT_ROOT / "validate_historical_debrief.py"
    analysis_json = analysis_output_path(database)

    stage_results: dict[str, str] = {}

    # --------------------------------------------------------
    # Deterministic analysis
    # --------------------------------------------------------
    analyze_signature = {
        "database": stat_signature(database),
        "analyzer": script_signature(analyzer),
    }
    reuse_analyze = (
        not args.force
        and not args.force_analyze
        and stage_is_reusable(
            state,
            "analyze",
            analyze_signature,
            required_paths=(analysis_json,),
        )
    )

    if reuse_analyze:
        stage_results["analyze"] = STATUS_REUSED
        print_stage("analyze", STATUS_REUSED, str(analysis_json))
    else:
        if args.dry_run:
            stage_results["analyze"] = STATUS_RUN
            print_stage("analyze", STATUS_RUN, "dry-run")
            print("+ " + " ".join([
                _quote_for_display(sys.executable),
                "analyze_telemetry.py",
                "--validate",
                _quote_for_display(str(database)),
            ]))
            return 0
        try:
            run_checked([
                sys.executable,
                str(analyzer),
                "--validate",
                str(database),
            ])
        except subprocess.CalledProcessError:
            stage_results["analyze"] = STATUS_FAILED
            print_stage("analyze", STATUS_FAILED)
            return 1
        if not analysis_json.is_file():
            raise RuntimeError(
                "analyze_telemetry terminó sin generar el JSON esperado: "
                f"{analysis_json}"
            )
        record_stage(
            state,
            "analyze",
            signature=analyze_signature,
            status=STATUS_RUN,
            output=str(analysis_json),
            details={"analysis_sha256": sha256_file(analysis_json)},
        )
        save_state(state_path, state)
        stage_results["analyze"] = STATUS_RUN
        print_stage("analyze", STATUS_RUN, str(analysis_json))

    analysis_sha = sha256_file(analysis_json)

    # --------------------------------------------------------
    # LLM + validator
    # --------------------------------------------------------
    llm_json: Path | None = None
    if args.no_llm:
        stage_results["llm"] = STATUS_SKIPPED
        stage_results["llm_validator"] = STATUS_SKIPPED
        print_stage("llm", STATUS_SKIPPED, "--no-llm")
    else:
        llm = llm_script(args.backend)
        llm_json = llm_output_path(analysis_json, args.backend)
        llm_signature = {
            "analysis_sha256": analysis_sha,
            "backend": args.backend,
            "model": llm_model_name(args.backend),
            "llm_script": script_signature(llm),
        }
        reuse_llm = (
            not args.force
            and not args.force_llm
            and stage_is_reusable(
                state,
                "llm",
                llm_signature,
                required_paths=(llm_json,),
            )
        )
        if reuse_llm:
            stage_results["llm"] = STATUS_REUSED
            print_stage("llm", STATUS_REUSED, str(llm_json))
        else:
            try:
                run_checked([
                    sys.executable,
                    str(llm),
                    str(analysis_json),
                ])
            except subprocess.CalledProcessError:
                stage_results["llm"] = STATUS_FAILED
                print_stage("llm", STATUS_FAILED)
                return 1
            if not llm_json.is_file():
                raise RuntimeError(
                    "El backend LLM terminó sin generar el JSON esperado: "
                    f"{llm_json}"
                )
            record_stage(
                state,
                "llm",
                signature=llm_signature,
                status=STATUS_RUN,
                output=str(llm_json),
                details={"llm_sha256": sha256_file(llm_json)},
            )
            save_state(state_path, state)
            stage_results["llm"] = STATUS_RUN
            print_stage("llm", STATUS_RUN, str(llm_json))

        validator_signature = {
            "llm_sha256": sha256_file(llm_json),
            "validator": script_signature(validator),
        }
        reuse_validator = (
            not args.force
            and stage_is_reusable(
                state,
                "llm_validator",
                validator_signature,
                required_paths=(llm_json,),
            )
        )
        if reuse_validator:
            stage_results["llm_validator"] = STATUS_REUSED
            print_stage("llm_validator", STATUS_REUSED)
        else:
            try:
                run_checked([
                    sys.executable,
                    str(validator),
                    str(llm_json),
                ])
            except subprocess.CalledProcessError:
                stage_results["llm_validator"] = STATUS_FAILED
                print_stage("llm_validator", STATUS_FAILED)
                return 1
            record_stage(
                state,
                "llm_validator",
                signature=validator_signature,
                status=STATUS_RUN,
                output=str(llm_json),
            )
            save_state(state_path, state)
            stage_results["llm_validator"] = STATUS_RUN
            print_stage("llm_validator", STATUS_RUN)

    # --------------------------------------------------------
    # History
    # --------------------------------------------------------
    current_session_id: int | None = None
    db_path = history_db_path(args.history_db)

    if args.no_history:
        stage_results["history"] = STATUS_SKIPPED
        stage_results["h3"] = STATUS_SKIPPED
        stage_results["h4"] = STATUS_SKIPPED
        stage_results["h5_1"] = STATUS_SKIPPED
        stage_results["h5_2"] = STATUS_SKIPPED
        stage_results["h5_2_llm"] = STATUS_SKIPPED
        stage_results["h5_3"] = STATUS_SKIPPED
        print_stage("history", STATUS_SKIPPED, "--no-history")
    else:
        db_before = stat_signature(db_path) if db_path.exists() else None
        history_signature = {
            "analysis_sha256": analysis_sha,
            "history_script": script_signature(history_script),
            "history_db": str(db_path),
            "history_db_before": db_before,
        }
        previous_history = (state.get("stages") or {}).get("history") or {}
        previous_details = previous_history.get("details") or {}
        stored_db_after = previous_details.get("history_db_after")
        current_db_sig = stat_signature(db_path) if db_path.exists() else None
        reuse_history = (
            not args.force
            and previous_history.get("signature", {}).get("analysis_sha256") == analysis_sha
            and previous_history.get("signature", {}).get("history_script") == script_signature(history_script)
            and previous_history.get("signature", {}).get("history_db") == str(db_path)
            and stored_db_after == current_db_sig
            and isinstance(previous_details.get("session_id"), int)
        )

        if reuse_history:
            current_session_id = int(previous_details["session_id"])
            stage_results["history"] = STATUS_REUSED
            print_stage("history", STATUS_REUSED, f"session_id={current_session_id}")
        else:
            result = import_history(analysis_json, db_path)
            current_session_id = int(result["session_id"])
            db_after = stat_signature(db_path)
            history_signature = {
                "analysis_sha256": analysis_sha,
                "history_script": script_signature(history_script),
                "history_db": str(db_path),
                "history_db_before": db_before,
            }
            record_stage(
                state,
                "history",
                signature=history_signature,
                status=STATUS_RUN,
                output=str(db_path),
                details={
                    "session_id": current_session_id,
                    "import_status": result.get("status"),
                    "history_db_after": db_after,
                },
            )
            save_state(state_path, state)
            stage_results["history"] = STATUS_RUN
            print_stage(
                "history",
                STATUS_RUN,
                f"{result.get('status')} / session_id={current_session_id}",
            )

        # H3 remains a calibration/batch-derived layer, not a mandatory per-session stage.
        stage_results["h3"] = STATUS_SKIPPED
        print_stage(
            "h3",
            STATUS_SKIPPED,
            "requiere un H2 matcher run calibrado; no se fuerza por sesión",
        )

        # ----------------------------------------------------
        # H4 historical reference
        # ----------------------------------------------------
        if args.no_historical_context:
            stage_results["h4"] = STATUS_SKIPPED
            stage_results["h5_1"] = STATUS_SKIPPED
            stage_results["h5_2"] = STATUS_SKIPPED
            stage_results["h5_2_llm"] = STATUS_SKIPPED
            stage_results["h5_3"] = STATUS_SKIPPED
            print_stage("h4", STATUS_SKIPPED, "--no-historical-context")
        else:
            applicable, reasons = h4_applicability(db_path, current_session_id)
            h4_output = historical_reference_output_path(database)
            if not applicable:
                stage_results["h4"] = STATUS_SKIPPED
                stage_results["h5_1"] = STATUS_SKIPPED
                stage_results["h5_2"] = STATUS_SKIPPED
                stage_results["h5_2_llm"] = STATUS_SKIPPED
                stage_results["h5_3"] = STATUS_SKIPPED
                print_stage("h4", STATUS_SKIPPED, ", ".join(reasons))
            else:
                h4_signature = {
                    "session_id": current_session_id,
                    "history_db": stat_signature(db_path),
                    "selector": script_signature(h4_script),
                }
                reuse_h4 = (
                    not args.force
                    and stage_is_reusable(
                        state,
                        "h4",
                        h4_signature,
                        required_paths=(h4_output,),
                    )
                )
                if reuse_h4:
                    stage_results["h4"] = STATUS_REUSED
                    print_stage("h4", STATUS_REUSED, str(h4_output))
                else:
                    try:
                        run_checked([
                            sys.executable,
                            str(h4_script),
                            str(current_session_id),
                            "--db",
                            str(db_path),
                            "--output",
                            str(h4_output),
                        ])
                    except subprocess.CalledProcessError:
                        stage_results["h4"] = STATUS_FAILED
                        print_stage("h4", STATUS_FAILED)
                        return 1
                    record_stage(
                        state,
                        "h4",
                        signature=h4_signature,
                        status=STATUS_RUN,
                        output=str(h4_output),
                        details={"h4_sha256": sha256_file(h4_output)},
                    )
                    save_state(state_path, state)
                    stage_results["h4"] = STATUS_RUN
                    print_stage("h4", STATUS_RUN, str(h4_output))

                # ------------------------------------------------
                # H5.1 dual reference context
                # ------------------------------------------------
                h5_output = dual_reference_output_path(database)
                h5_signature = {
                    "analysis_sha256": analysis_sha,
                    "h4_sha256": sha256_file(h4_output),
                    "builder": script_signature(h5_script),
                }
                reuse_h5 = (
                    not args.force
                    and stage_is_reusable(
                        state,
                        "h5_1",
                        h5_signature,
                        required_paths=(h5_output,),
                    )
                )
                if reuse_h5:
                    stage_results["h5_1"] = STATUS_REUSED
                    print_stage("h5_1", STATUS_REUSED, str(h5_output))
                else:
                    try:
                        run_checked([
                            sys.executable,
                            str(h5_script),
                            str(analysis_json),
                            str(h4_output),
                            "--output",
                            str(h5_output),
                        ])
                    except subprocess.CalledProcessError:
                        stage_results["h5_1"] = STATUS_FAILED
                        print_stage("h5_1", STATUS_FAILED)
                        return 1
                    record_stage(
                        state,
                        "h5_1",
                        signature=h5_signature,
                        status=STATUS_RUN,
                        output=str(h5_output),
                    )
                    save_state(state_path, state)
                    stage_results["h5_1"] = STATUS_RUN
                    print_stage("h5_1", STATUS_RUN, str(h5_output))

                # ------------------------------------------------
                # H5.2 raw cross-session comparison
                # ------------------------------------------------
                try:
                    h5_2_pair = resolve_cross_session_pair(
                        h5_output,
                        db_path,
                        PROJECT_ROOT / "telemetria",
                    )
                except CrossSessionNotApplicableError as exc:
                    stage_results["h5_2"] = STATUS_SKIPPED
                    stage_results["h5_2_llm"] = STATUS_SKIPPED
                    stage_results["h5_3"] = STATUS_SKIPPED
                    print_stage("h5_2", STATUS_SKIPPED, str(exc))
                else:
                    h5_2_output = cross_session_output_path(database)
                    h5_2_signature = {
                        "h5_1_sha256": sha256_file(h5_output),
                        "history_db": stat_signature(db_path),
                        "current_raw": stat_signature(h5_2_pair["current"]["database"]),
                        "historical_raw": stat_signature(
                            h5_2_pair["historical"]["database"]
                        ),
                        "builder": script_signature(h5_2_script),
                        "validator": script_signature(h5_2_validator),
                        "delta_comparison": script_signature(
                            PROJECT_ROOT / "delta_comparison.py"
                        ),
                        "sector_analysis": script_signature(
                            PROJECT_ROOT / "sector_analysis.py"
                        ),
                    }
                    reuse_h5_2 = (
                        not args.force
                        and stage_is_reusable(
                            state,
                            "h5_2",
                            h5_2_signature,
                            required_paths=(h5_2_output,),
                        )
                    )
                    if reuse_h5_2:
                        stage_results["h5_2"] = STATUS_REUSED
                        print_stage("h5_2", STATUS_REUSED, str(h5_2_output))
                    else:
                        try:
                            run_checked([
                                sys.executable,
                                str(h5_2_script),
                                str(h5_output),
                                "--history-db",
                                str(db_path),
                                "--telemetry-dir",
                                str(PROJECT_ROOT / "telemetria"),
                                "--output",
                                str(h5_2_output),
                            ])
                            run_checked([
                                sys.executable,
                                str(h5_2_validator),
                                str(h5_2_output),
                            ])
                        except subprocess.CalledProcessError:
                            stage_results["h5_2"] = STATUS_FAILED
                            print_stage("h5_2", STATUS_FAILED)
                            return 1
                        record_stage(
                            state,
                            "h5_2",
                            signature=h5_2_signature,
                            status=STATUS_RUN,
                            output=str(h5_2_output),
                            details={"h5_2_sha256": sha256_file(h5_2_output)},
                        )
                        save_state(state_path, state)
                        stage_results["h5_2"] = STATUS_RUN
                        print_stage("h5_2", STATUS_RUN, str(h5_2_output))

                    # --------------------------------------------
                    # H5.2 LLM historical narrative (observational)
                    # --------------------------------------------
                    if args.no_llm:
                        stage_results["h5_2_llm"] = STATUS_SKIPPED
                        print_stage("h5_2_llm", STATUS_SKIPPED, "--no-llm")
                    else:
                        h5_2_llm_output = historical_llm_output_path(
                            database,
                            backend=args.backend,
                            model=llm_model_name(args.backend),
                        )
                        h5_2_llm_signature = {
                            "h5_2_sha256": sha256_file(h5_2_output),
                            "backend": args.backend,
                            "model": llm_model_name(args.backend),
                            "generator": script_signature(h5_2_llm_script),
                            "validator": script_signature(h5_2_llm_validator),
                            "backend_script": script_signature(
                                llm_script(args.backend)
                            ),
                        }
                        previous_h5_2_llm = (
                            (state.get("stages") or {}).get("h5_2_llm") or {}
                        )
                        previous_h5_2_llm_sha = (
                            previous_h5_2_llm.get("details") or {}
                        ).get("h5_2_llm_sha256")
                        reuse_h5_2_llm = (
                            not args.force
                            and not args.force_llm
                            and stage_is_reusable(
                                state,
                                "h5_2_llm",
                                h5_2_llm_signature,
                                required_paths=(h5_2_llm_output,),
                            )
                            and previous_h5_2_llm_sha
                            == sha256_file(h5_2_llm_output)
                        )
                        if reuse_h5_2_llm:
                            stage_results["h5_2_llm"] = STATUS_REUSED
                            print_stage(
                                "h5_2_llm",
                                STATUS_REUSED,
                                str(h5_2_llm_output),
                            )
                        else:
                            try:
                                run_checked([
                                    sys.executable,
                                    str(h5_2_llm_script),
                                    str(h5_2_output),
                                    "--backend",
                                    args.backend,
                                    "--output",
                                    str(h5_2_llm_output),
                                    "--debug-dir",
                                    str(
                                        historical_llm_debug_dir(
                                            database,
                                            backend=args.backend,
                                        )
                                    ),
                                ])
                                run_checked([
                                    sys.executable,
                                    str(h5_2_llm_validator),
                                    str(h5_2_llm_output),
                                ])
                            except subprocess.CalledProcessError:
                                stage_results["h5_2_llm"] = STATUS_FAILED
                                print_stage("h5_2_llm", STATUS_FAILED)
                                return 1
                            record_stage(
                                state,
                                "h5_2_llm",
                                signature=h5_2_llm_signature,
                                status=STATUS_RUN,
                                output=str(h5_2_llm_output),
                                details={
                                    "h5_2_llm_sha256": sha256_file(h5_2_llm_output)
                                },
                            )
                            save_state(state_path, state)
                            stage_results["h5_2_llm"] = STATUS_RUN
                            print_stage(
                                "h5_2_llm",
                                STATUS_RUN,
                                str(h5_2_llm_output),
                            )

                    # ------------------------------------------
                    # H5.3 historical section (observational, deterministic)
                    # ------------------------------------------
                    h5_3_candidates = h5_3_candidates_path(database)
                    h5_3_section = h5_3_section_path(database)
                    h5_3_signature = {
                        "h5_1_sha256": sha256_file(h5_output),
                        "h5_2_sha256": sha256_file(h5_2_output),
                        "candidate_builder": script_signature(
                            h5_3_candidate_script
                        ),
                        "renderer": script_signature(h5_3_render_script),
                        "validator": script_signature(h5_3_validator_script),
                    }
                    reuse_h5_3 = (
                        not args.force
                        and stage_is_reusable(
                            state,
                            "h5_3",
                            h5_3_signature,
                            required_paths=(h5_3_candidates, h5_3_section),
                        )
                    )
                    if reuse_h5_3:
                        stage_results["h5_3"] = STATUS_REUSED
                        print_stage("h5_3", STATUS_REUSED, str(h5_3_section))
                    else:
                        try:
                            run_checked([
                                sys.executable,
                                str(h5_3_candidate_script),
                                str(h5_output),
                                str(h5_2_output),
                                "--output",
                                str(h5_3_candidates),
                            ])
                            run_checked([
                                sys.executable,
                                str(h5_3_render_script),
                                str(h5_output),
                                str(h5_2_output),
                                "--output",
                                str(h5_3_section),
                            ])
                            run_checked([
                                sys.executable,
                                str(h5_3_validator_script),
                                str(h5_3_section),
                            ])
                        except subprocess.CalledProcessError:
                            stage_results["h5_3"] = STATUS_FAILED
                            print_stage("h5_3", STATUS_FAILED)
                            return 1
                        record_stage(
                            state,
                            "h5_3",
                            signature=h5_3_signature,
                            status=STATUS_RUN,
                            output=str(h5_3_section),
                            details={
                                "candidates_sha256": sha256_file(
                                    h5_3_candidates
                                ),
                                "section_sha256": sha256_file(h5_3_section),
                            },
                        )
                        save_state(state_path, state)
                        stage_results["h5_3"] = STATUS_RUN
                        print_stage("h5_3", STATUS_RUN, str(h5_3_section))

    state["last_summary"] = stage_results
    save_state(state_path, state)

    print()
    print("=" * 72)
    print(f"RACE ENGINEER ORCHESTRATOR v{ORCHESTRATOR_VERSION}")
    print("=" * 72)
    for name, status in stage_results.items():
        print(f"{name:16s} {status}")
    if stage_results.get("h5_3") in {STATUS_RUN, STATUS_REUSED}:
        section_path = h5_3_section_path(database)
        if section_path.is_file():
            section = json.loads(section_path.read_text(encoding="utf-8"))
            print()
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass
            print(section.get("rendered_section", ""))
    print(f"state: {state_path}")
    print("RESULT: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orquestador operativo de Race Engineer."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="DuckDB -> análisis -> LLM -> History -> H4 -> H5.1 -> H5.2 -> narrativa -> sección histórica H5.3",
    )
    analyze.add_argument("database", help="DuckDB de telemetría, normalmente telemetria\\archivo.duckdb")
    analyze.add_argument(
        "--backend",
        choices=("deepseek", "ollama"),
        default="deepseek",
        help="Backend LLM. Default: deepseek.",
    )
    analyze.add_argument("--history-db", default=None)
    analyze.add_argument("--force", action="store_true", help="Reejecutar todas las etapas aplicables.")
    analyze.add_argument("--force-analyze", action="store_true")
    analyze.add_argument("--force-llm", action="store_true")
    analyze.add_argument("--no-llm", action="store_true")
    analyze.add_argument("--no-history", action="store_true")
    analyze.add_argument("--no-historical-context", action="store_true")
    analyze.add_argument("--dry-run", action="store_true")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "analyze":
        return analyze_command(args)
    raise RuntimeError(f"Comando no implementado: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
