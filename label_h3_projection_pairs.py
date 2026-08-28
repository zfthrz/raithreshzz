"""Human label entry point for isolated H3.2 projection review queues."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import label_episode_pairs as base


REVIEW_SCOPE = "H3_2_PROJECTION_VALIDATION_ONLY"


def load_projection_queue(path: Path) -> dict[str, Any]:
    data = base.load_queue(path)
    metadata = data.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("review_scope") != REVIEW_SCOPE:
        raise ValueError("La cola no pertenece al scope aislado de revisión H3.2.")
    if metadata.get("labels_authorize_matcher_calibration") is not False:
        raise ValueError("La cola no desactiva autoridad de calibración del matcher.")
    if metadata.get("labels_authorize_h3_membership") is not False:
        raise ValueError("La cola no desactiva persistencia de membresía H3.")
    return data


def load_projection_labels(
    path: Path,
    queue_path: Path,
    reviewer: str | None,
) -> dict[str, Any]:
    existed = path.exists()
    data = base.load_labels(path, queue_path, reviewer)
    metadata = data["metadata"]
    if existed and metadata.get("review_scope") != REVIEW_SCOPE:
        raise ValueError("Los labels existentes no pertenecen a la revisión H3.2.")
    metadata["review_scope"] = REVIEW_SCOPE
    metadata["labels_authorize_matcher_calibration"] = False
    metadata["labels_authorize_h3_membership"] = False
    metadata["affects_next_stint_plan"] = False
    metadata["historical_actions_authorized"] = False
    metadata["semantics"] = (
        "Human H3.2 projection review using SAME/DIFFERENT/AMBIGUOUS/SKIP. "
        "Labels are evidence only and do not calibrate the matcher or persist H3 "
        "membership automatically."
    )
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Etiqueta pares proyectados H3.2 sin autoridad automática."
    )
    parser.add_argument("queue_json", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--include-skipped", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    queue_path = args.queue_json.resolve()
    labels_path = (
        args.labels.resolve()
        if args.labels is not None
        else queue_path.with_name("pair_labels.json")
    )
    queue = load_projection_queue(queue_path)
    labels = load_projection_labels(
        labels_path, queue_path, args.reviewer
    )
    if args.summary:
        base.print_summary(labels)
        return 0
    return base.interactive_review(
        queue,
        labels,
        labels_path,
        include_skipped_on_resume=args.include_skipped,
    )


if __name__ == "__main__":
    raise SystemExit(main())
