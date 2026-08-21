from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    message: str

@dataclass(frozen=True)
class AuditResult:
    path: str
    status: str
    issues: list[AuditIssue]
    summary: dict[str, Any]
    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "status": self.status,
                "issues": [asdict(x) for x in self.issues], "summary": self.summary}

def _d(v): return v if isinstance(v, dict) else {}
def _l(v): return v if isinstance(v, list) else []
def _canon(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _labels(items):
    return [str(x.get("plan_label")) if isinstance(x, dict) and x.get("plan_label") is not None else None for x in items]

def audit_payload(payload: dict[str, Any], *, path="<memory>") -> AuditResult:
    issues: list[AuditIssue] = []
    md = _d(payload.get("metadata"))
    structured = md.get("structured_validation")
    factual = md.get("factual_grounding_validation")
    if structured != "PASS":
        issues.append(AuditIssue("ERROR","STRUCTURED_VALIDATION_NOT_PASS",f"structured_validation={structured!r}"))
    if factual != "PASS":
        issues.append(AuditIssue("ERROR","FACTUAL_GROUNDING_NOT_PASS",f"factual_grounding_validation={factual!r}"))

    plan = _l(payload.get("next_stint_plan"))
    p10 = _d(payload.get("next_stint_plan_presentation"))
    p10m = _d(p10.get("_p10_presentation"))
    pres = _l(p10.get("presentation"))
    p10s = p10m.get("status")

    if p10s == "ACTIVE":
        if p10m.get("item_count") != len(pres):
            issues.append(AuditIssue("ERROR","P10_ITEM_COUNT_MISMATCH",
                f"item_count={p10m.get('item_count')!r}, presentation={len(pres)}"))
        ranks = []
        rank_error = False
        for item in pres:
            rank = _d(item.get("_p9_presentation_metadata") if isinstance(item, dict) else {}).get("presentation_rank")
            if not isinstance(rank, int):
                rank_error = True
                break
            ranks.append(rank)
        if rank_error:
            issues.append(AuditIssue("ERROR","P10_PRESENTATION_RANK_MISSING","ACTIVE P10 item missing integer presentation_rank"))
        elif ranks != list(range(len(pres))):
            issues.append(AuditIssue("ERROR","P10_PRESENTATION_RANK_INVALID",f"ranks={ranks!r}"))
        if plan and sorted(map(_canon, plan)) != sorted(map(_canon, pres)):
            issues.append(AuditIssue("ERROR","P10_NOT_A_PROJECTION_OF_PLAN",
                "P10 presentation differs structurally from next_stint_plan"))
    elif p10s not in (None, "FALLBACK_ORIGINAL_ORDER"):
        issues.append(AuditIssue("WARN","P10_UNKNOWN_STATUS",f"status={p10s!r}"))

    p11 = _d(payload.get("next_stint_focus"))
    p11s = p11.get("status")
    focus = _l(p11.get("items"))
    count = p11.get("focus_count")

    if p11s == "ACTIVE":
        if count != len(focus):
            issues.append(AuditIssue("ERROR","P11_FOCUS_COUNT_MISMATCH",f"focus_count={count!r}, items={len(focus)}"))
        if len(focus) > 2:
            issues.append(AuditIssue("ERROR","P11_TOO_MANY_ITEMS",f"items={len(focus)}"))
        if p10s != "ACTIVE":
            issues.append(AuditIssue("ERROR","P11_ACTIVE_WITHOUT_ACTIVE_P10",f"P10={p10s!r}"))
        elif focus != pres[:2]:
            issues.append(AuditIssue("ERROR","P11_NOT_P10_PREFIX","P11 items are not exactly P10 presentation[:2]"))
    elif p11s == "UNAVAILABLE":
        if focus:
            issues.append(AuditIssue("ERROR","P11_UNAVAILABLE_HAS_ITEMS","UNAVAILABLE P11 must have []"))
        if count not in (0, None):
            issues.append(AuditIssue("ERROR","P11_UNAVAILABLE_NONZERO_COUNT",f"focus_count={count!r}"))
    elif p11s is None:
        issues.append(AuditIssue("WARN","P11_MISSING","next_stint_focus is missing"))
    else:
        issues.append(AuditIssue("WARN","P11_UNKNOWN_STATUS",f"status={p11s!r}"))

    summary = {
        "track": md.get("track"), "reference_lap": md.get("reference_lap"),
        "plan_labels": _labels(plan), "presentation_labels": _labels(pres),
        "focus_labels": _labels(focus), "p10_status": p10s, "p11_status": p11s,
    }
    status = "FAIL" if any(x.severity == "ERROR" for x in issues) else "PASS"
    return AuditResult(path, status, issues, summary)

def audit_file(path: Path) -> AuditResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object")
    except Exception as exc:
        return AuditResult(str(path),"FAIL",[AuditIssue("ERROR","JSON_READ_ERROR",str(exc))],{})
    return audit_payload(payload, path=str(path))

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--json-report", type=Path)
    ap.add_argument("--strict-warnings", action="store_true")
    args = ap.parse_args(argv)
    paths = []
    for raw in args.inputs:
        p = Path(raw)
        paths += sorted(p.rglob("*.json")) if p.is_dir() else [p]
    results = [audit_file(p) for p in paths]
    for r in results:
        print(f"[{r.status}] {r.path}")
        if r.summary:
            print(f"  P10={r.summary['presentation_labels']} P11={r.summary['focus_labels']}")
        for i in r.issues:
            print(f"  {i.severity} {i.code}: {i.message}")
    report = {
        "file_count": len(results),
        "pass_count": sum(r.status == "PASS" for r in results),
        "fail_count": sum(r.status == "FAIL" for r in results),
        "warning_count": sum(i.severity == "WARN" for r in results for i in r.issues),
        "results": [r.to_dict() for r in results],
    }
    print(f"\nFiles={report['file_count']} PASS={report['pass_count']} FAIL={report['fail_count']} WARN={report['warning_count']}")
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    if report["fail_count"] or (args.strict_warnings and report["warning_count"]):
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
