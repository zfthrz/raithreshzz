"""Prepare an isolated human-review queue for generated H3.2 projections.

The queue reuses the H2 SAME/DIFFERENT/AMBIGUOUS/SKIP review semantics, but its
local output is explicitly excluded from matcher calibration and H3 authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import episode_pair_features
from pair_review_queue import QUEUE_SCHEMA_VERSION, stable_pair_id
from runtime_paths import generated_root, history_db_default_path, local_root


REVIEW_VERSION = "0.1"
SELECTION_FILENAME = "persistent_pattern_selection.json"
EXPECTED_BASIS = "calibrated_h2_match_to_pattern_representative"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def collect_projection_references(
    generated: Path,
    *,
    track: str | None = None,
    track_layout: str | None = None,
    vehicle_variant: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    references: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(
        (generated / "h3_1").glob(f"*/{SELECTION_FILENAME}")
    ):
        document = _load(path)
        metadata = document.get("metadata") if isinstance(document, dict) else None
        projected = (
            document.get("projected_pattern_matches")
            if isinstance(document, dict)
            else None
        )
        if not isinstance(metadata, dict) or not isinstance(projected, list):
            errors.append(f"invalid_selection:{path}")
            continue
        context = metadata.get("context")
        if not isinstance(context, dict):
            errors.append(f"invalid_context:{path}")
            continue
        values = (
            context.get("track"),
            context.get("track_layout"),
            context.get("vehicle_variant"),
        )
        if not all(isinstance(value, str) and value for value in values):
            errors.append(f"incomplete_context:{path}")
            continue
        if track is not None and values[0] != track:
            continue
        if track_layout is not None and values[1] != track_layout:
            continue
        if vehicle_variant is not None and values[2] != vehicle_variant:
            continue
        authority_valid = (
            metadata.get("observational_only") is True
            and metadata.get("affects_next_stint_plan") is False
            and metadata.get("historical_actions_authorized") is False
        )
        if not authority_valid:
            errors.append(f"authority_invalid:{path}")
            continue
        session_id = metadata.get("session_id")
        if not isinstance(session_id, int):
            errors.append(f"invalid_session_id:{path}")
            continue
        provenance = document.get("provenance")
        bundle_hash = (
            provenance.get("source_bundle_sha256")
            if isinstance(provenance, dict)
            else None
        )
        selection_hash = file_sha256(path)
        for index, item in enumerate(projected):
            if not isinstance(item, dict):
                errors.append(f"invalid_projection:{path}:{index}")
                continue
            representative = item.get("representative_member")
            current = item.get("current_session_episode")
            decision = item.get("matcher_decision")
            pattern_id = item.get("pattern_id")
            contract_valid = (
                item.get("match_basis") == EXPECTED_BASIS
                and isinstance(pattern_id, str)
                and bool(pattern_id)
                and isinstance(representative, dict)
                and isinstance(representative.get("session_id"), int)
                and isinstance(representative.get("episode_pk"), int)
                and isinstance(current, dict)
                and isinstance(current.get("episode_pk"), int)
                and isinstance(decision, dict)
                and decision.get("decision") == "MATCH"
                and decision.get("automatic") is True
            )
            if not contract_valid:
                errors.append(f"projection_contract_invalid:{path}:{index}")
                continue
            references.append(
                {
                    "context": {
                        "track": values[0],
                        "track_layout": values[1],
                        "vehicle_variant": values[2],
                    },
                    "pattern_id": pattern_id,
                    "pattern_state": item.get("state"),
                    "representative_session_id": representative["session_id"],
                    "representative_episode_pk": representative["episode_pk"],
                    "current_session_id": session_id,
                    "current_episode_pk": current["episode_pk"],
                    "matcher_decision": decision,
                    "source_selection_path": str(path.resolve()),
                    "source_selection_sha256": selection_hash,
                    "source_bundle_sha256": bundle_hash,
                    "projection_snapshot_sha256": _snapshot_sha256(item),
                }
            )
    references.sort(
        key=lambda item: (
            item["context"]["track"],
            item["context"]["track_layout"],
            item["context"]["vehicle_variant"],
            item["pattern_id"],
            item["current_session_id"],
            item["current_episode_pk"],
        )
    )
    return references, errors


def build_review_items(
    references: list[dict[str, Any]],
    pair_builder: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    by_pair_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for reference in references:
        features = pair_builder(reference)
        expected = (
            reference["representative_session_id"],
            reference["representative_episode_pk"],
            reference["current_session_id"],
            reference["current_episode_pk"],
        )
        actual = (
            features.get("session_a"),
            features.get("episode_pk_a"),
            features.get("session_b"),
            features.get("episode_pk_b"),
        )
        if actual != expected:
            raise ValueError(
                f"Par reconstruido no coincide con proyección: {actual} != {expected}"
            )
        pair_id = stable_pair_id(features)
        evidence = {
            key: reference[key]
            for key in (
                "context",
                "pattern_id",
                "pattern_state",
                "representative_session_id",
                "representative_episode_pk",
                "current_session_id",
                "current_episode_pk",
                "matcher_decision",
                "source_selection_path",
                "source_selection_sha256",
                "source_bundle_sha256",
                "projection_snapshot_sha256",
            )
        }
        if pair_id not in by_pair_id:
            by_pair_id[pair_id] = {
                "pair_id": pair_id,
                "queue_position": 0,
                "selected_by": [
                    {"lens": "h3_2_calibrated_projection", "rank": 0}
                ],
                "features": features,
                "review_scope": "H3_2_PROJECTION_VALIDATION_ONLY",
                "h3_projection_evidence": [],
            }
            order.append(pair_id)
        by_pair_id[pair_id]["h3_projection_evidence"].append(evidence)

    items = [by_pair_id[pair_id] for pair_id in order]
    for position, item in enumerate(items, start=1):
        item["queue_position"] = position
        item["selected_by"][0]["rank"] = position
        item["h3_projection_evidence"].sort(
            key=lambda value: (
                value["pattern_id"],
                value["current_session_id"],
                value["current_episode_pk"],
            )
        )
    return items


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def prepare_review_queue(
    *,
    generated: Path,
    history_db: Path,
    output: Path,
    track: str | None = None,
    track_layout: str | None = None,
    vehicle_variant: str | None = None,
) -> dict[str, Any]:
    references, errors = collect_projection_references(
        generated,
        track=track,
        track_layout=track_layout,
        vehicle_variant=vehicle_variant,
    )
    if errors:
        raise ValueError("Proyecciones inválidas: " + "; ".join(errors))
    if not references:
        raise ValueError("No hay proyecciones H3.2 válidas para el filtro solicitado.")

    import duckdb

    connection = duckdb.connect(str(history_db), read_only=True)
    try:
        channel_sets = episode_pair_features.load_episode_channels(connection)
        channel_metrics = episode_pair_features.load_channel_metrics(connection)
        episode_maps: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}

        def pair_builder(reference: dict[str, Any]) -> dict[str, Any]:
            context = reference["context"]
            key = (
                context["track"],
                context["track_layout"],
                context["vehicle_variant"],
            )
            if key not in episode_maps:
                episodes = episode_pair_features.load_episodes(
                    connection,
                    track=key[0],
                    track_layout=key[1],
                    vehicle_variant=key[2],
                )
                episode_maps[key] = {
                    int(item["episode_pk"]): item for item in episodes
                }
            episodes = episode_maps[key]
            representative = episodes.get(reference["representative_episode_pk"])
            current = episodes.get(reference["current_episode_pk"])
            if representative is None or current is None:
                raise ValueError(
                    "History no contiene un episodio recomendado requerido por "
                    f"la proyección {reference['pattern_id']}."
                )
            return episode_pair_features.build_pair_record(
                representative, current, channel_sets, channel_metrics
            )

        items = build_review_items(references, pair_builder)
    finally:
        connection.close()

    source_files = sorted({
        (item["source_selection_path"], item["source_selection_sha256"])
        for item in references
    })
    document = {
        "metadata": {
            "queue_schema_version": QUEUE_SCHEMA_VERSION,
            "h3_projection_review_version": REVIEW_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "review_scope": "H3_2_PROJECTION_VALIDATION_ONLY",
            "valid_labels": ["SAME", "DIFFERENT", "AMBIGUOUS", "SKIP"],
            "label_semantics_source": "label_episode_pairs.py",
            "source_projection_edge_count": len(references),
            "selected_pair_count": len(items),
            "selection_policy": "all_valid_projection_edges_no_threshold_no_sampling",
            "filters": {
                "track": track,
                "track_layout": track_layout,
                "vehicle_variant": vehicle_variant,
            },
            "history_db_path": str(history_db.resolve()),
            "history_db_sha256": file_sha256(history_db),
            "source_selections": [
                {"path": path, "sha256": sha256}
                for path, sha256 in source_files
            ],
            "observational_only": True,
            "labels_authorize_matcher_calibration": False,
            "labels_authorize_h3_membership": False,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "semantics": (
                "Human review of existing H3.2 projected episode pairs. SAME means "
                "same general location and driving-difference type; no label changes "
                "matcher thresholds or persists H3 membership automatically."
            ),
        },
        "queue": items,
    }
    _atomic_write(output, document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepara una cola humana aislada para proyecciones H3.2."
    )
    parser.add_argument("--generated-root", type=Path, default=generated_root())
    parser.add_argument("--history-db", type=Path, default=history_db_default_path())
    parser.add_argument(
        "--output",
        type=Path,
        default=local_root() / "h3_projection_review" / "pair_review_queue.json",
    )
    parser.add_argument("--track")
    parser.add_argument("--track-layout")
    parser.add_argument("--vehicle-variant")
    args = parser.parse_args()
    document = prepare_review_queue(
        generated=args.generated_root,
        history_db=args.history_db,
        output=args.output,
        track=args.track,
        track_layout=args.track_layout,
        vehicle_variant=args.vehicle_variant,
    )
    metadata = document["metadata"]
    print("=" * 76)
    print(f"RACE ENGINEER - H3.2 PROJECTION HUMAN REVIEW v{REVIEW_VERSION}")
    print("=" * 76)
    print(f"Projection edges: {metadata['source_projection_edge_count']}")
    print(f"Unique pairs:     {metadata['selected_pair_count']}")
    print(f"Output:           {args.output.resolve()}")
    print("Labels:           SAME / DIFFERENT / AMBIGUOUS / SKIP")
    print("Authority:        HUMAN REVIEW ONLY / NO AUTOMATIC PROMOTION")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
