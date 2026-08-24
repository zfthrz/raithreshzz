#!/usr/bin/env python3
"""Read-only model/backend observability for Race Engineer (Phase I).

Métricas deterministas sobre artefactos existentes (sin llamadas LLM):
- cantidad de debriefs por backend/modelo;
- validator pass rate (PASS / STALE_RENDER / FAIL) usando
  validate_llm_analysis_output.py;
- retries/repairs a partir de llm_debug (`*_attempt_N.txt`).

Tokens/cost/latencia NO están en los artefactos: requieren un benchmark con
inputs idénticos (CALIBRATION SESSION RECOMMENDED según roadmap).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


OBSERVABILITY_VERSION = "0.1"
STALE_RENDER_MARKER = (
    "global_analysis no coincide exactamente con el renderizador determinista de Python."
)
_ATTEMPT_RE = re.compile(r"_attempt_(\d+)\.txt$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_backend_model(filename: str) -> tuple[str, str]:
    """Backend/modelo desde el filename de llm_results."""
    marker = "_llm_analysis_v3_10_8_5_4_"
    if marker in filename:
        tail = filename.split(marker, 1)[1].rsplit(".json", 1)[0]
    else:
        tail = filename
    if tail.startswith("deepseek_v2_"):
        return "deepseek", tail[len("deepseek_v2_") :]
    if tail.startswith("llamacpp_"):
        return "llamacpp", tail[len("llamacpp_") :]
    return "ollama", tail


def parse_debug_attempts(files: list[str]) -> dict[str, Any]:
    """Estadísticas de retries por llamada desde nombres de archivos debug."""
    call_attempts: dict[str, list[int]] = defaultdict(list)
    for name in files:
        match = _ATTEMPT_RE.search(name)
        if not match:
            continue
        attempt = int(match.group(1))
        call = name[: match.start()]
        call_attempts[call].append(attempt)
    retried_calls = 0
    total_calls = 0
    attempts_sum = 0
    max_attempts = 0
    for call, attempts in call_attempts.items():
        total_calls += 1
        top = max(attempts)
        attempts_sum += len(attempts)
        max_attempts = max(max_attempts, top)
        if top > 1:
            retried_calls += 1
    return {
        "calls": total_calls,
        "prompt_files": attempts_sum,
        "retried_calls": retried_calls,
        "retry_rate": (
            round(retried_calls / total_calls, 4) if total_calls else 0.0
        ),
        "max_attempts": max_attempts,
    }


def run_validation(
    path: Path,
    *,
    validator_script: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    completed = runner(
        [sys.executable, str(validator_script), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode == 0:
        return "PASS"
    output = (completed.stdout or "") + (completed.stderr or "")
    if STALE_RENDER_MARKER in output:
        return "STALE_RENDER"
    return "FAIL"


def collect(
    llm_root: Path,
    debug_root: Path,
    validator_script: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    results = list(llm_root.glob("*/*.json"))
    by_backend: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "artifacts": 0,
            "validation": Counter(),
            "calls": 0,
            "retried_calls": 0,
            "retry_rate": 0.0,
            "max_attempts": 0,
        }
    )
    per_artifact: list[dict[str, Any]] = []
    status_by_path: dict[Path, str] = {}
    for path in sorted(results):
        backend, model = derive_backend_model(path.name)
        status = run_validation(
            path,
            validator_script=validator_script,
            runner=runner,
        )
        status_by_path[path] = status
        row = by_backend[backend]
        row["artifacts"] += 1
        row["validation"][status] += 1
        per_artifact.append(
            {
                "session": path.parent.name,
                "backend": backend,
                "model": model,
                "validator": status,
            }
        )

    # Retries por backend desde llm_debug/<session>/<backend>/...
    for session_dir in sorted(debug_root.iterdir()):
        if not session_dir.is_dir():
            continue
        for backend_dir in sorted(session_dir.iterdir()):
            if not backend_dir.is_dir():
                continue
            files = [path.name for path in backend_dir.glob("*.txt")]
            stats = parse_debug_attempts(files)
            row = by_backend[backend_dir.name]
            row["calls"] += stats["calls"]
            row["retried_calls"] += stats["retried_calls"]
            row["max_attempts"] = max(row["max_attempts"], stats["max_attempts"])

    models: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"artifacts": 0, "validation": Counter()}
    )
    for path in sorted(results):
        backend, model = derive_backend_model(path.name)
        status = status_by_path[path]
        row = models[f"{backend}/{model}"]
        row["artifacts"] += 1
        row["validation"][status] += 1

    for backend, row in by_backend.items():
        total = row["calls"]
        row["retry_rate"] = (
            round(row["retried_calls"] / total, 4) if total else 0.0
        )

    return {
        "version": OBSERVABILITY_VERSION,
        "generated_at_utc": utc_now_iso(),
        "policy": {
            "read_only": True,
            "no_llm_called": True,
            "no_ranking_change_authorized": True,
        },
        "summary": {
            "artifacts": len(results),
            "by_backend": {
                backend: {
                    **{
                        key: dict(value)
                        if isinstance(value, Counter)
                        else value
                        for key, value in row.items()
                    }
                }
                for backend, row in sorted(by_backend.items())
            },
            "by_model": {
                model: {
                    "artifacts": row["artifacts"],
                    "validation": dict(row["validation"]),
                }
                for model, row in sorted(models.items())
            },
        },
        "per_artifact": per_artifact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Observabilidad read-only de modelos/backends (Phase I)."
    )
    parser.add_argument("--llm-root", default="data/generated/llm_results")
    parser.add_argument("--debug-root", default="data/generated/llm_debug")
    parser.add_argument("--validator", default="validate_llm_analysis_output.py")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = collect(
        Path(args.llm_root),
        Path(args.debug_root),
        Path(args.validator),
    )
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Output: {output}")

    print("=" * 88)
    print(f"MODEL OBSERVABILITY v{OBSERVABILITY_VERSION}")
    print("=" * 88)
    for backend, row in report["summary"]["by_backend"].items():
        validation = row["validation"]
        print(
            f"{backend:10} artifacts={row['artifacts']} "
            f"PASS={validation.get('PASS', 0)} STALE={validation.get('STALE_RENDER', 0)} "
            f"FAIL={validation.get('FAIL', 0)} calls={row['calls']} "
            f"retries={row['retried_calls']} retry_rate={row['retry_rate']}"
        )
    print("Tokens/cost/latencia: no disponibles en artefactos (benchmark requerido).")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
