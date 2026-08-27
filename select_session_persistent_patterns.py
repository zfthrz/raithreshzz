from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


H3_SESSION_SELECTOR_VERSION = "0.1"
RECURRENT_STATES = {"persistent_pattern", "cross_session_repeat"}


def _json_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def select_session_patterns(connection, session_id: int) -> dict[str, Any]:
    session = connection.execute(
        """
        SELECT track, COALESCE(lmu_track_layout, track), vehicle_variant
        FROM sessions WHERE session_id = ?
        """,
        [session_id],
    ).fetchone()
    if session is None:
        raise ValueError(f"History no contiene session_id={session_id}.")

    track, track_layout, vehicle_variant = session
    context = {
        "track": track,
        "track_layout": track_layout,
        "vehicle_variant": vehicle_variant,
    }
    if not all(isinstance(value, str) and value for value in context.values()):
        return _document(
            session_id=session_id,
            context=context,
            status="CONTEXT_UNAVAILABLE",
        )

    run = connection.execute(
        """
        SELECT pattern_run_id, h3_version, matcher_version,
               source_bundle_sha256, imported_at_utc
        FROM pattern_runs
        WHERE track = ? AND track_layout = ? AND vehicle_variant = ?
        ORDER BY pattern_run_id DESC
        LIMIT 1
        """,
        [track, track_layout, vehicle_variant],
    ).fetchone()
    if run is None:
        return _document(
            session_id=session_id,
            context=context,
            status="NO_COMPATIBLE_PATTERN_RUN",
        )

    pattern_run_id = int(run[0])
    rows = connection.execute(
        """
        SELECT
            p.pattern_id, p.state, p.observation_count,
            p.independent_session_count, p.center_median_m,
            p.center_spread_m, p.start_median_m, p.end_median_m,
            p.action_time_loss_median_s, p.common_action_channels_json,
            p.union_action_channels_json, p.session_ids_json,
            m.episode_pk, m.episode_id, m.start_distance_m,
            m.end_distance_m, m.center_distance_m, m.action_time_loss_s,
            m.channels_json
        FROM persistent_pattern_members AS m
        JOIN persistent_patterns AS p
          ON p.pattern_pk = m.pattern_pk
         AND p.pattern_run_id = m.pattern_run_id
         AND p.pattern_id = m.pattern_id
        WHERE m.pattern_run_id = ? AND m.session_id = ?
        ORDER BY
            CASE p.state
                WHEN 'persistent_pattern' THEN 0
                WHEN 'cross_session_repeat' THEN 1
                WHEN 'single_observation' THEN 2
                ELSE 3
            END,
            p.center_median_m, p.pattern_id, m.episode_pk
        """,
        [pattern_run_id, session_id],
    ).fetchall()

    matches = []
    for row in rows:
        matches.append(
            {
                "pattern_id": row[0],
                "state": row[1],
                "observation_count": int(row[2]),
                "independent_session_count": int(row[3]),
                "pattern_location": {
                    "center_median_m": row[4],
                    "center_spread_m": row[5],
                    "start_median_m": row[6],
                    "end_median_m": row[7],
                },
                "action_time_loss_median_s": row[8],
                "common_action_channels": _json_list(row[9]),
                "union_action_channels": _json_list(row[10]),
                "independent_session_ids": _json_list(row[11]),
                "current_session_member": {
                    "episode_pk": int(row[12]),
                    "episode_id": row[13],
                    "start_distance_m": row[14],
                    "end_distance_m": row[15],
                    "center_distance_m": row[16],
                    "action_time_loss_s": row[17],
                    "channels": _json_list(row[18]),
                },
                "match_basis": "exact_pattern_member_identity",
            }
        )

    provenance = {
        "pattern_run_id": pattern_run_id,
        "h3_version": run[1],
        "matcher_version": run[2],
        "source_bundle_sha256": run[3],
        "pattern_run_imported_at_utc": run[4],
    }
    status = "MATCHED_PATTERN_MEMBERSHIP" if matches else "NO_PATTERN_MEMBERSHIP"
    return _document(
        session_id=session_id,
        context=context,
        status=status,
        provenance=provenance,
        matches=matches,
    )


def _document(
    *,
    session_id: int,
    context: dict[str, Any],
    status: str,
    provenance: dict[str, Any] | None = None,
    matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    matches = matches or []
    recurrent = [item for item in matches if item.get("state") in RECURRENT_STATES]
    return {
        "metadata": {
            "selector_version": H3_SESSION_SELECTOR_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "session_id": session_id,
            "context": context,
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
            "matching_policy": "exact membership in latest compatible imported pattern run",
        },
        "provenance": provenance,
        "summary": {
            "matched_pattern_count": len(matches),
            "recurrent_pattern_count": len(recurrent),
            "single_observation_count": sum(
                item.get("state") == "single_observation" for item in matches
            ),
        },
        "matched_patterns": matches,
    }


def write_selection(db_path: Path, session_id: int, output: Path) -> dict[str, Any]:
    import duckdb

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        document = select_session_patterns(connection, session_id)
    finally:
        connection.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Selecciona membresías H3 persistentes para una sesión de History."
    )
    parser.add_argument("session_id", type=int)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    document = write_selection(args.db, args.session_id, args.output)
    metadata = document["metadata"]
    print("=" * 80)
    print("RACE ENGINEER - H3.1 SESSION PERSISTENT PATTERN SELECTOR v0.1")
    print("=" * 80)
    print(f"Session:             {args.session_id}")
    print(f"Status:              {metadata['status']}")
    print(f"Matched patterns:    {document['summary']['matched_pattern_count']}")
    print(f"Recurrent patterns:  {document['summary']['recurrent_pattern_count']}")
    print(f"Output:              {args.output.resolve()}")
    print("Authority:           OBSERVATIONAL ONLY")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
