from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import llm_analysis as renderer
from validate_llm_analysis_output import validate_file


RERENDER_VERSION = "0.1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("la raíz JSON debe ser un objeto")
    return document


def rebuild_document(
    document: dict[str, Any],
    *,
    source_path: Path,
) -> dict[str, Any]:
    rebuilt = copy.deepcopy(document)
    facts = rebuilt.get("session_coaching_facts")
    if not isinstance(facts, dict):
        raise ValueError("session_coaching_facts ausente o inválido")
    plan = facts.get("next_stint_plan")
    if not isinstance(plan, list):
        raise ValueError("next_stint_plan ausente o inválido")

    for index, item in enumerate(plan):
        if not isinstance(item, dict):
            raise ValueError(f"next_stint_plan[{index}] inválido")
        cues = renderer.build_driver_cues_for_plan_item(item)
        item["driver_cues"] = cues
        item["actionable_cue_count"] = len(cues)

    policy = facts.get("session_priority_policy")
    if not isinstance(policy, dict):
        raise ValueError("session_priority_policy ausente o inválido")
    policy["actionability_policy_version"] = (
        renderer.SESSION_ACTIONABILITY_POLICY_VERSION
    )

    structured = rebuilt.get("global_structured")
    if not isinstance(structured, dict):
        raise ValueError("global_structured ausente o inválido")
    structured["repeated_observations"] = (
        renderer.build_deterministic_repeated_observations(facts)
    )
    structured["next_session_priorities"] = (
        renderer.build_deterministic_next_session_priorities(facts)
    )
    rebuilt["global_analysis"] = renderer.render_global_analysis(
        rebuilt.get("metadata", {}),
        rebuilt.get("comparisons", []),
        facts,
        structured,
    )

    metadata = rebuilt.setdefault("metadata", {})
    metadata["deterministic_rerender"] = {
        "version": RERENDER_VERSION,
        "source_path": str(source_path.resolve()),
        "source_sha256": sha256_file(source_path),
        "actionability_policy_version": (
            renderer.SESSION_ACTIONABILITY_POLICY_VERSION
        ),
        "llm_called": False,
    }
    return rebuilt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruye hechos y render deterministas sin llamar al LLM"
    )
    parser.add_argument("source_json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        source = args.source_json.resolve(strict=True)
        output = args.output.resolve()
        if source == output:
            raise ValueError("source y output deben ser archivos distintos")
        if output.exists() and not args.overwrite:
            raise ValueError("output ya existe; use --overwrite para reemplazarlo")
        rebuilt = rebuild_document(load_json(source), source_path=source)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        errors, warnings = validate_file(output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RESULT: FAIL — {exc}")
        return 2

    print("=" * 88)
    print("RACE ENGINEER - DETERMINISTIC LLM RERENDER v0.1")
    print("=" * 88)
    print(f"Source: {source}")
    print(f"Output: {output}")
    print("LLM called: NO")
    print(f"Validator errors: {len(errors)}")
    print(f"Validator warnings: {len(warnings)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
