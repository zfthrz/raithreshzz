from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "repository"
JSON_REPORT = REPORT_DIR / "repository_inventory.json"
MARKDOWN_REPORT = REPORT_DIR / "repository_inventory.md"
EXCLUDED_PATHS = {
    "docs/repository/repository_inventory.json",
    "docs/repository/repository_inventory.md",
}
LARGE_FILE_BYTES = 10 * 1024 * 1024
VERSIONED_PYTHON_RE = re.compile(r"(?:^|_)v\d+(?:_\d+)+(?:_|\.py$)", re.IGNORECASE)
SESSION_JSON_RE = re.compile(r"_\d{4}-\d{2}-\d{2}T\d{2}_\d{2}_\d{2}Z(?:\(\d+\))?\.json$", re.IGNORECASE)


def run_git(*args: str) -> bytes:
    command = [
        "git",
        "-c",
        f"safe.directory={ROOT}",
        "-C",
        str(ROOT),
        *args,
    ]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Git command failed: {' '.join(args)}\n{message}")
    return completed.stdout


def git_paths(*args: str) -> set[str]:
    raw = run_git(*args, "-z")
    return {
        item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for item in raw.split(b"\0")
        if item
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_repository_files() -> list[Path]:
    files: list[Path] = []
    for current_root, directories, names in os.walk(ROOT, followlinks=False):
        current = Path(current_root)
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in sorted(names):
            path = current / name
            relative = path.relative_to(ROOT).as_posix()
            if relative in EXCLUDED_PATHS:
                continue
            files.append(path)
    return files


def classify(relative: str, status: str) -> tuple[str, list[str], str | None]:
    path = PurePosixPath(relative)
    lower = relative.lower()
    reasons: list[str] = []
    proposed_destination: str | None = None

    if status == "ignored":
        return "KEEP_LOCAL_UNTRACKED", ["Ignored by Git"], None

    if path.parts and path.parts[0] == "legacy":
        return "KEEP", ["Historical material under legacy/; never auto-move"], None

    if "calibration_batches" in path.parts:
        return "REVIEW_REQUIRED", ["Calibration material may contain human labels or source data"], None

    if path.suffix.lower() == ".duckdb" and status == "tracked":
        reasons.append("Tracked DuckDB database may be local runtime state")

    if any(part.lower().endswith("_llm") for part in path.parts) and status == "tracked":
        reasons.append("Tracked *_llm output")

    if len(path.parts) == 1 and SESSION_JSON_RE.search(path.name):
        reasons.append("Root-level timestamped session JSON")
        proposed_destination = f"data/sessions/{path.name}"

    if len(path.parts) == 1 and path.suffix.lower() == ".py" and VERSIONED_PYTHON_RE.search(path.name):
        reasons.append("Root-level versioned Python artifact")
        proposed_destination = f"legacy/python_releases/{path.name}"

    if reasons:
        return "REVIEW_REQUIRED", reasons, proposed_destination

    if status == "untracked":
        return "REVIEW_REQUIRED", ["Untracked file requires an explicit keep/ignore decision"], None

    return "KEEP", [], None


def suspicious_name_reasons(relative: str) -> list[str]:
    reasons: list[str] = []
    for part in PurePosixPath(relative).parts:
        if part != part.strip():
            reasons.append("leading or trailing whitespace")
        if any(character in part for character in ('"', "'", "`")):
            reasons.append("quote character")
        if any(ord(character) < 32 for character in part):
            reasons.append("control character")
    return sorted(set(reasons))


def build_inventory() -> dict[str, Any]:
    tracked = git_paths("ls-files", "--cached")
    untracked = git_paths("ls-files", "--others", "--exclude-standard")
    ignored = git_paths("ls-files", "--others", "--ignored", "--exclude-standard")
    head = run_git("rev-parse", "HEAD").decode("ascii").strip()
    branch = run_git("branch", "--show-current").decode("utf-8", errors="replace").strip()

    entries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    hashes: dict[str, list[str]] = defaultdict(list)

    for path in iter_repository_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in tracked:
            status = "tracked"
        elif relative in ignored:
            status = "ignored"
        elif relative in untracked:
            status = "untracked"
        else:
            status = "unclassified"

        try:
            is_symlink = path.is_symlink()
            size = path.lstat().st_size
            digest = None if is_symlink else sha256_file(path)
            category, reasons, proposed_destination = classify(relative, status)
            name_reasons = suspicious_name_reasons(relative)
            entry = {
                "path": relative,
                "size_bytes": size,
                "sha256": digest,
                "git_status": status,
                "category": category,
                "reasons": reasons,
                "proposed_destination": proposed_destination,
                "is_symlink": is_symlink,
                "large_file": size >= LARGE_FILE_BYTES,
                "suspicious_name": bool(name_reasons),
                "suspicious_name_reasons": name_reasons,
            }
            entries.append(entry)
            if digest:
                hashes[digest].append(relative)
        except OSError as exc:
            errors.append({"path": relative, "error": str(exc)})

    duplicate_groups = [
        {"sha256": digest, "paths": sorted(paths), "copies": len(paths)}
        for digest, paths in hashes.items()
        if len(paths) > 1
    ]
    duplicate_groups.sort(key=lambda item: item["paths"])

    status_counts = Counter(entry["git_status"] for entry in entries)
    category_counts = Counter(entry["category"] for entry in entries)
    summary = {
        "total_files": len(entries),
        "total_size_bytes": sum(entry["size_bytes"] for entry in entries),
        "git_status_counts": dict(sorted(status_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "large_files": sum(entry["large_file"] for entry in entries),
        "suspicious_names": sum(entry["suspicious_name"] for entry in entries),
        "symlinks": sum(entry["is_symlink"] for entry in entries),
        "duplicate_groups": len(duplicate_groups),
        "scan_errors": len(errors),
    }
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": str(ROOT),
        "git": {"head": head, "branch": branch},
        "safety": {
            "mode": "read-only audit",
            "existing_files_moved": 0,
            "existing_files_deleted": 0,
            "files_untracked": 0,
            "note": "Only the two inventory report files are written.",
        },
        "summary": summary,
        "duplicates": duplicate_groups,
        "errors": errors,
        "files": entries,
    }


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def markdown_report(inventory: dict[str, Any]) -> str:
    summary = inventory["summary"]
    status = summary["git_status_counts"]
    categories = summary["category_counts"]
    review = [entry for entry in inventory["files"] if entry["category"] == "REVIEW_REQUIRED"]
    large = [entry for entry in inventory["files"] if entry["large_file"]]
    suspicious = [entry for entry in inventory["files"] if entry["suspicious_name"]]

    lines = [
        "# Repository inventory",
        "",
        "> Safe audit: no existing files were moved, deleted, or untracked.",
        "",
        "## Summary",
        "",
        f"- Commit: `{inventory['git']['head']}`",
        f"- Branch: `{inventory['git']['branch'] or '(detached HEAD)'}`",
        f"- Total files: {summary['total_files']}",
        f"- Total size: {format_bytes(summary['total_size_bytes'])}",
        f"- Tracked: {status.get('tracked', 0)}",
        f"- Untracked: {status.get('untracked', 0)}",
        f"- Ignored: {status.get('ignored', 0)}",
        f"- Keep: {categories.get('KEEP', 0)}",
        f"- Keep local/untracked: {categories.get('KEEP_LOCAL_UNTRACKED', 0)}",
        f"- Review required: {categories.get('REVIEW_REQUIRED', 0)}",
        f"- Exact duplicate groups: {summary['duplicate_groups']}",
        f"- Files at least {format_bytes(LARGE_FILE_BYTES)}: {summary['large_files']}",
        f"- Suspicious names: {summary['suspicious_names']}",
        f"- Scan errors: {summary['scan_errors']}",
        "",
        "## Review required",
        "",
    ]
    if review:
        for entry in review:
            reason = "; ".join(entry["reasons"])
            destination = entry["proposed_destination"]
            suffix = f"; proposed destination: `{destination}`" if destination else ""
            lines.append(f"- `{entry['path']}` — {reason}{suffix}")
    else:
        lines.append("- None detected.")

    lines.extend(["", "## Exact duplicate groups", ""])
    if inventory["duplicates"]:
        for group in inventory["duplicates"]:
            lines.append(f"- `{group['sha256']}`")
            for path in group["paths"]:
                lines.append(f"  - `{path}`")
    else:
        lines.append("- None detected.")

    lines.extend(["", "## Large files", ""])
    if large:
        for entry in sorted(large, key=lambda item: item["size_bytes"], reverse=True):
            lines.append(f"- `{entry['path']}` — {format_bytes(entry['size_bytes'])}")
    else:
        lines.append("- None detected.")

    lines.extend(["", "## Suspicious names", ""])
    if suspicious:
        for entry in suspicious:
            reasons = ", ".join(entry["suspicious_name_reasons"])
            lines.append(f"- `{entry['path']}` — {reasons}")
    else:
        lines.append("- None detected.")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `KEEP` means no automated action is proposed.",
            "- `KEEP_LOCAL_UNTRACKED` means Git already ignores the file; this audit does not change it.",
            "- `REVIEW_REQUIRED` is a finding, not permission to move or delete anything.",
            "- Proposed destinations are suggestions only and are never applied by `audit`.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(inventory: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_REPORT.write_text(markdown_report(inventory), encoding="utf-8")


def audit() -> int:
    inventory = build_inventory()
    write_reports(inventory)
    summary = inventory["summary"]
    print("PASS - audit completed; no existing files changed")
    print(f"Files inventoried: {summary['total_files']}")
    print(f"Review required: {summary['category_counts'].get('REVIEW_REQUIRED', 0)}")
    print(f"Duplicate groups: {summary['duplicate_groups']}")
    print(f"JSON: {JSON_REPORT.relative_to(ROOT)}")
    print(f"Markdown: {MARKDOWN_REPORT.relative_to(ROOT)}")
    if summary["scan_errors"]:
        print("WARNING - some files could not be scanned; inspect the JSON report")
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safe repository inventory. Audit never moves, deletes, or untracks existing files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("audit", help="Create JSON and Markdown inventory reports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "audit":
        return audit()
    raise AssertionError("unreachable")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"FAILED - no destructive action was performed\n{exc}", file=sys.stderr)
        raise SystemExit(1)
