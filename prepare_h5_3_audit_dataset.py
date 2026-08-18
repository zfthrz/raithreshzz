from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


DATASET_SCHEMA_VERSION = "1.0"
DATASET_VERSION = "0.1"
EXPECTED_BUILDER_VERSION = "0.1"
SHADOW_STATUS = "SHADOW_OBSERVATIONAL_ONLY"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: la raíz JSON debe ser un objeto.")
    return payload


def _known(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_artifact(
    artifact_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    payload = load_json(artifact_path)
    metadata = payload.get("metadata") or {}
    if payload.get("status") != SHADOW_STATUS:
        raise ValueError(f"{artifact_path}: status no es {SHADOW_STATUS}")
    if metadata.get("builder_version") != EXPECTED_BUILDER_VERSION:
        raise ValueError(
            f"{artifact_path}: builder_version no soportada "
            f"({metadata.get('builder_version')!r})"
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError(f"{artifact_path}: candidates ausente/inválido")
    prerequisites = payload.get("prerequisites") or {}
    if not prerequisites.get("applicable"):
        return payload, [], prerequisites.get("skip_reason")
    return payload, candidates, None


def _audit_record(
    artifact_path: Path,
    artifact_sha256: str,
    payload: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError(f"{artifact_path}: candidato {index} inválido")
    candidate_id = candidate.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError(f"{artifact_path}: candidato {index} sin candidate_id")
    location = candidate.get("location") or {}
    current = candidate.get("current_minus_historical") or {}
    total_delta = payload.get("total_delta") or {}
    context = payload.get("context") or {}
    channel_evidence = candidate.get("observational_channel_evidence")
    if not isinstance(channel_evidence, dict):
        channel_evidence = {}
    return {
        "audit_id": f"{artifact_sha256[:12]}:{candidate_id}",
        "candidate_id": candidate_id,
        "source_artifact_sha256": artifact_sha256,
        "source_artifact_path": str(artifact_path.resolve()),
        "context": {
            "track": _known(context.get("track")),
            "track_layout": _known(context.get("track_layout")),
            "vehicle_variant": _known(context.get("vehicle_variant")),
            "car_name_raw": _known(context.get("car_name_raw")),
        },
        "delta_sign": total_delta.get("sign"),
        "current_minus_historical_s": total_delta.get("current_minus_historical_s"),
        "location_label": _known(location.get("label")) or "UNNAMED",
        "evidence": {
            "delta_change_s": current.get("delta_change_s"),
            "start_distance_m": current.get("start_distance_m"),
            "end_distance_m": current.get("end_distance_m"),
        },
        "observational_channel_evidence": dict(channel_evidence),
        "label": None,
    }


def build_dataset(artifact_paths: list[Path]) -> dict[str, Any]:
    if not artifact_paths:
        raise ValueError("Se requiere al menos un artefacto H5.3a.")

    ordered = sorted(
        (Path(path).resolve() for path in artifact_paths),
        key=lambda path: str(path).casefold(),
    )
    sources: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen_audit_ids: set[str] = set()

    for artifact_path in ordered:
        artifact_sha256 = sha256_file(artifact_path)
        payload, extracted, skip_reason = _extract_artifact(artifact_path)
        records: list[dict[str, Any]] = []
        for index, candidate in enumerate(extracted):
            record = _audit_record(
                artifact_path,
                artifact_sha256,
                payload,
                candidate,
                index,
            )
            audit_id = record["audit_id"]
            if audit_id in seen_audit_ids:
                raise ValueError(f"audit_id duplicado: {audit_id}")
            seen_audit_ids.add(audit_id)
            records.append(record)
        candidates.extend(records)
        sources.append(
            {
                "path": str(artifact_path),
                "sha256": artifact_sha256,
                "candidate_count": len(records),
                "skip_reason": skip_reason,
            }
        )

    sign_counts = Counter(
        record["delta_sign"] for record in candidates if record["delta_sign"]
    )
    track_counts = Counter(
        str(record["context"].get("track")) for record in candidates
    )
    context_counts = Counter(
        (
            str(record["context"].get("track")),
            str(record["context"].get("track_layout")),
            str(record["context"].get("vehicle_variant")),
        )
        for record in candidates
    )
    coverage = {
        "candidate_count": len(candidates),
        "source_artifact_count": len(ordered),
        "tracks": dict(track_counts),
        "delta_signs": dict(sign_counts),
        "contexts": {
            " | ".join(context): count
            for context, count in sorted(context_counts.items())
        },
        "both_signs_covered": bool(
            sign_counts.get("current_slower") and sign_counts.get("current_faster")
        ),
    }

    return {
        "metadata": {
            "schema_version": DATASET_SCHEMA_VERSION,
            "dataset_version": DATASET_VERSION,
            "source_artifact_count": len(ordered),
            "policy": {
                "human_review_is_ground_truth": True,
                "no_threshold_from_single_context": True,
                "candidates_are_shadow": True,
            },
        },
        "sources": sources,
        "coverage": coverage,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H5.3b: arma dataset reproducible de candidatos H5.3a para auditoría humana."
    )
    parser.add_argument("artifacts", nargs="+", help="Artefactos H5.3a JSON.")
    parser.add_argument("--output", default="h5_3_audit_dataset.json")
    args = parser.parse_args()

    payload = build_dataset([Path(path) for path in args.artifacts])
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    coverage = payload["coverage"]
    print("=" * 88)
    print(f"RACE ENGINEER - H5.3b AUDIT DATASET v{DATASET_VERSION}")
    print("=" * 88)
    print(f"Candidates: {coverage['candidate_count']}")
    print(f"Sources: {coverage['source_artifact_count']}")
    print(f"Delta signs: {coverage['delta_signs']}")
    print(f"Both signs covered: {coverage['both_signs_covered']}")
    print(f"Output: {output_path}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
