#!/usr/bin/env python3
"""Run an opt-in LLM episode-prompt experiment without touching production outputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from llm_prompt_shadow_policy import (
    SHADOW_AUTHORITY,
    SHADOW_PROMPT_POLICY_VERSION,
    build_shadow_episode_system_prompt,
    prompt_sha256,
)


RUNNER_VERSION = "0.1"
BACKEND_MODULES = {
    "deepseek": "llm_analysis_deepseek",
    "ollama": "llm_analysis_ingenierov3",
    "llamacpp": "llm_analysis_llamacpp",
}


@dataclass(frozen=True)
class ShadowRunPlan:
    input_path: Path
    backend: str
    module_name: str
    model_override: str | None
    api_model_override: str | None
    policy: str
    output_dir: Path
    debug_dir: Path
    source_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_utf8_output(*streams: Any) -> None:
    """Prevent Windows legacy console encodings from aborting a completed run."""

    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _path_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part).casefold()


def build_run_plan(
    input_path: Path,
    backend: str,
    output_root: Path,
    model_override: str | None = None,
    api_model_override: str | None = None,
) -> ShadowRunPlan:
    source = input_path.resolve()
    if not source.is_file():
        raise ValueError(f"analysis JSON does not exist: {source}")
    if source.suffix.casefold() != ".json":
        raise ValueError(f"analysis source must be JSON: {source}")
    if backend not in BACKEND_MODULES:
        raise ValueError(f"unsupported backend: {backend}")

    model = model_override.strip() if isinstance(model_override, str) else None
    api_model = (
        api_model_override.strip()
        if isinstance(api_model_override, str)
        else None
    )
    if model_override is not None and not model:
        raise ValueError("model override must be a non-empty string")
    if api_model_override is not None and not api_model:
        raise ValueError("API model override must be a non-empty string")
    if api_model and backend != "llamacpp":
        raise ValueError("API model override is only supported for llamacpp")

    output_parent = output_root.resolve() / SHADOW_PROMPT_POLICY_VERSION / backend
    if model:
        output_parent = output_parent / _path_slug(model)
    output_dir = output_parent / source.stem
    return ShadowRunPlan(
        input_path=source,
        backend=backend,
        module_name=BACKEND_MODULES[backend],
        model_override=model,
        api_model_override=api_model,
        policy=SHADOW_PROMPT_POLICY_VERSION,
        output_dir=output_dir,
        debug_dir=output_dir / "debug",
        source_sha256=_sha256_file(source),
    )


def configure_shadow_module(module: ModuleType, plan: ShadowRunPlan) -> str:
    """Install process-local prompt/output hooks and return the shadow prompt hash."""

    production_prompt = getattr(module, "EPISODE_SYSTEM_PROMPT", None)
    shadow_prompt = build_shadow_episode_system_prompt(production_prompt)
    shadow_prompt_hash = prompt_sha256(shadow_prompt)
    module.EPISODE_SYSTEM_PROMPT = shadow_prompt
    if plan.model_override:
        module.MODEL_NAME = plan.model_override
    if plan.api_model_override:
        original_llamacpp_chat = getattr(module, "llamacpp_chat", None)
        if not callable(original_llamacpp_chat):
            raise ValueError("llamacpp module does not expose llamacpp_chat")

        def shadow_llamacpp_chat(*args: Any, **kwargs: Any):
            artifact_model = module.MODEL_NAME
            module.MODEL_NAME = plan.api_model_override
            try:
                return original_llamacpp_chat(*args, **kwargs)
            finally:
                module.MODEL_NAME = artifact_model

        module.llamacpp_chat = shadow_llamacpp_chat

    module.llm_result_dir = lambda _input_path: plan.output_dir
    # The shadow output is already backend-scoped. Ignore any legacy backend
    # label supplied by a runtime module so debug files cannot escape or land
    # under a misleading sibling directory.
    module.llm_debug_dir = lambda _input_path, backend=None: plan.debug_dir

    original_save_result = module.save_result

    def save_shadow_result(*args: Any, **kwargs: Any):
        result = original_save_result(*args, **kwargs)
        output_path = Path(result[0])
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        metadata = payload.setdefault("metadata", {})
        metadata["backend"] = plan.backend
        metadata["prompt_shadow"] = {
            "runner_version": RUNNER_VERSION,
            "policy": plan.policy,
            "authority": SHADOW_AUTHORITY,
            "episode_prompt_sha256": shadow_prompt_hash,
            "source_json_sha256": plan.source_sha256,
            "model_override": plan.model_override,
            "api_model_override": plan.api_model_override,
            "production_output_modified": False,
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result

    module.save_result = save_shadow_result
    return shadow_prompt_hash


def _print_plan(plan: ShadowRunPlan, *, execute: bool) -> None:
    print("=" * 88)
    print(f"RACE ENGINEER - LLM PROMPT SHADOW RUNNER v{RUNNER_VERSION}")
    print("=" * 88)
    print(f"Mode: {'EXECUTE' if execute else 'PLAN_ONLY'}")
    print(f"Authority: {SHADOW_AUTHORITY}")
    print(f"Policy: {plan.policy}")
    print(f"Backend module: {plan.backend} / {plan.module_name}")
    print(f"Model override: {plan.model_override or 'MODULE_DEFAULT'}")
    print(f"API model override: {plan.api_model_override or 'MODULE_DEFAULT'}")
    print(f"Source: {plan.input_path}")
    print(f"Source SHA-256: {plan.source_sha256}")
    print(f"Output: {plan.output_dir}")
    print("Production output modified: NO")


def main(argv: list[str] | None = None) -> int:
    configure_utf8_output(sys.stdout, sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="deterministic analysis JSON")
    parser.add_argument("--backend", choices=sorted(BACKEND_MODULES), required=True)
    parser.add_argument(
        "--model",
        help="explicit model identifier recorded in the shadow artifact",
    )
    parser.add_argument(
        "--api-model",
        help="exact llama.cpp API model id, kept separate from the artifact label",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/generated/llm_prompt_shadow"),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="explicitly authorize the backend LLM call; otherwise only print the plan",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow replacing an existing shadow result for this policy/backend/source",
    )
    args = parser.parse_args(argv)

    try:
        plan = build_run_plan(
            args.input,
            args.backend,
            args.output_root,
            model_override=args.model,
            api_model_override=args.api_model,
        )
    except ValueError as exc:
        parser.error(str(exc))

    _print_plan(plan, execute=args.execute)
    if not args.execute:
        print("RESULT: PLAN_ONLY - no LLM called and no files written")
        return 0

    existing = list(plan.output_dir.glob("*.json")) if plan.output_dir.exists() else []
    if existing and not args.force:
        print("RESULT: BLOCKED_EXISTING_SHADOW_OUTPUT")
        for path in existing:
            print(f"  {path}")
        print("Use --force only if replacing this local shadow result is intentional.")
        return 2

    module = importlib.import_module(plan.module_name)
    shadow_prompt_hash = configure_shadow_module(module, plan)
    print(f"Shadow episode prompt SHA-256: {shadow_prompt_hash}")

    original_argv = sys.argv[:]
    try:
        sys.argv = [str(Path(module.__file__).resolve()), str(plan.input_path)]
        module.main()
    finally:
        sys.argv = original_argv

    print(f"RESULT: PASS - shadow output only: {plan.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
