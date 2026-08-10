from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)

def main() -> int:
    run(sys.executable, "scripts/check_project.py")

    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "history.duckdb")
        run(sys.executable, "session_history.py", "--db", db, "init")
        run(
            sys.executable,
            "session_history.py",
            "--db",
            db,
            "import",
            "examples/monza_analyze_v3_8.json",
        )
        run(sys.executable, "validate_history_db.py", "--db", db)

        # Idempotency: second import must not create a second session.
        run(
            sys.executable,
            "session_history.py",
            "--db",
            db,
            "import",
            "examples/monza_analyze_v3_8.json",
        )

    print("PORTABLE SMOKE TEST: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
