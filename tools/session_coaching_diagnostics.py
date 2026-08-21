
from __future__ import annotations
import argparse, csv, json
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class SessionDiagnostic:
    path: str
    track: str | None
    model: str | None
    p10_status: Any
    p10_reordered: Any
    focus_status: Any
    focus_count: int
    plan_families: list[str]
    presentation_families: list[str]
    focus_families: list[str]
    focus_labels: list[str]
    repeated_family_count: int
    distinct_focus_family_count: int
    structured_validation: Any
    factual_grounding_validation: Any

    def to_dict(self):
        return asdict(self)

def _d(v): return v if isinstance(v, dict) else {}
def _l(v): return v if isinstance(v, list) else []

def _family(item):
    if not isinstance(item, dict): return "UNKNOWN"
    value = _d(item.get("_p9_presentation_metadata")).get("primary_action_family")
    return value.strip() if isinstance(value, str) and value.strip() else "UNKNOWN"

def _label(item):
    if not isinstance(item, dict): return "?"
    value = item.get("plan_label")
    return str(value) if value is not None else "?"

def diagnose_payload(payload: dict[str, Any], path="<memory>"):
    md = _d(payload.get("metadata"))
    plan = _l(payload.get("next_stint_plan"))
    p10 = _d(payload.get("next_stint_plan_presentation"))
    pres = _l(p10.get("presentation"))
    p10m = _d(p10.get("_p10_presentation"))
    p11 = _d(payload.get("next_stint_focus"))
    focus = _l(p11.get("items"))

    repeated = sum(
        1 for item in pres
        if isinstance(item, dict)
        and _d(item.get("_p9_presentation_metadata")).get("redundancy_status") == "REPEATED_FAMILY"
    )
    ff = [_family(x) for x in focus]
    return SessionDiagnostic(
        path=str(path),
        track=md.get("track"),
        model=md.get("model"),
        p10_status=p10m.get("status"),
        p10_reordered=p10m.get("reordered"),
        focus_status=p11.get("status"),
        focus_count=len(focus),
        plan_families=[_family(x) for x in plan],
        presentation_families=[_family(x) for x in pres],
        focus_families=ff,
        focus_labels=[_label(x) for x in focus],
        repeated_family_count=repeated,
        distinct_focus_family_count=len(set(ff)) if ff else 0,
        structured_validation=md.get("structured_validation"),
        factual_grounding_validation=md.get("factual_grounding_validation"),
    )

def diagnose_file(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be object")
    return diagnose_payload(payload, path)

def aggregate_sessions(sessions):
    plan = Counter()
    pres = Counter()
    focus = Counter()
    slots = defaultdict(Counter)
    tracks = Counter()
    track_focus = defaultdict(Counter)
    p10_active = p10_reordered = p11_active = 0
    diverse = duplicate = 0
    structured = factual = 0

    for s in sessions:
        track = s.track or "UNKNOWN"
        tracks[track] += 1
        plan.update(s.plan_families)
        pres.update(s.presentation_families)
        focus.update(s.focus_families)
        for idx, fam in enumerate(s.focus_families, 1):
            slots[f"slot_{idx}"][fam] += 1
            track_focus[track][fam] += 1
        p10_active += s.p10_status == "ACTIVE"
        p10_reordered += s.p10_reordered is True
        p11_active += s.focus_status == "ACTIVE"
        structured += s.structured_validation == "PASS"
        factual += s.factual_grounding_validation == "PASS"
        if s.focus_count == 2:
            if s.distinct_focus_family_count == 2: diverse += 1
            elif s.distinct_focus_family_count == 1: duplicate += 1

    two = diverse + duplicate
    return {
        "session_count": len(sessions),
        "validation": {"structured_pass_count": structured, "factual_grounding_pass_count": factual},
        "p10": {
            "active_count": p10_active,
            "reordered_count": p10_reordered,
            "reordered_rate": (p10_reordered / p10_active) if p10_active else None,
        },
        "p11": {
            "active_count": p11_active,
            "two_focus_sessions": two,
            "diverse_two_focus_sessions": diverse,
            "duplicate_two_focus_sessions": duplicate,
            "two_focus_diversity_rate": (diverse / two) if two else None,
        },
        "family_counts": {
            "plan": dict(plan.most_common()),
            "presentation": dict(pres.most_common()),
            "focus": dict(focus.most_common()),
            "focus_slots": {k: dict(v.most_common()) for k, v in sorted(slots.items())},
        },
        "tracks": {
            track: {
                "session_count": count,
                "focus_family_counts": dict(track_focus[track].most_common()),
            }
            for track, count in sorted(tracks.items())
        },
    }

def _expand(values):
    out, seen = [], set()
    for raw in values:
        p = Path(raw)
        candidates = sorted(p.rglob("*.json")) if p.is_dir() else [p]
        for c in candidates:
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                out.append(c)
    return out

def print_report(a):
    print("SESSION COACHING DIAGNOSTICS")
    print("=" * 40)
    print(f"Sessions: {a['session_count']}")
    print(f"P10 reordered: {a['p10']['reordered_count']}/{a['p10']['active_count']}")
    print(
        f"P11 two-focus: {a['p11']['two_focus_sessions']} | "
        f"diverse={a['p11']['diverse_two_focus_sessions']} | "
        f"duplicate-family={a['p11']['duplicate_two_focus_sessions']}"
    )
    print("Focus families:", a["family_counts"]["focus"])
    print("Focus slots:", a["family_counts"]["focus_slots"])
    print("Tracks:", a["tracks"])

def write_csv(path, sessions):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [s.to_dict() for s in sessions]
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            for key in ("plan_families","presentation_families","focus_families","focus_labels"):
                row[key] = "|".join(row[key])
            w.writerow(row)

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--json-report", type=Path)
    ap.add_argument("--csv-report", type=Path)
    args = ap.parse_args(argv)

    sessions, errors = [], []
    for path in _expand(args.inputs):
        try:
            sessions.append(diagnose_file(path))
        except Exception as exc:
            errors.append((str(path), str(exc)))

    if not sessions:
        for p,e in errors: print(f"ERROR {p}: {e}")
        return 2

    agg = aggregate_sessions(sessions)
    print_report(agg)

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps({"aggregate":agg,"sessions":[s.to_dict() for s in sessions],"read_errors":errors},
                       indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    if args.csv_report:
        write_csv(args.csv_report, sessions)
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
