from pathlib import Path

import import_h3_context as module
from h3_import_readiness import H3Context, H3_IMPORTED, H3_READY_TO_IMPORT


CONTEXT = H3Context("Spa", "Spa", "LMP2_ELMS")


def ready_row(tmp_path: Path):
    patterns = tmp_path / "persistent_patterns.json"
    matches = tmp_path / "episode_pair_matches.json"
    patterns.write_text("{}", encoding="utf-8")
    matches.write_text("{}", encoding="utf-8")
    return {
        "status": H3_READY_TO_IMPORT,
        "patterns_path": str(patterns),
        "matches_path": str(matches),
    }


def test_read_only_exact_context_never_backs_up_or_imports(tmp_path, monkeypatch):
    history = tmp_path / "history.duckdb"
    history.write_bytes(b"history")
    row = ready_row(tmp_path)
    monkeypatch.setattr(module, "audit_input_fingerprint", lambda **kwargs: "fresh")

    report, code = module.import_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=history,
        readiness_discoverer=lambda **kwargs: {CONTEXT: row},
        backupper=lambda *_: (_ for _ in ()).throw(AssertionError("backup called")),
        importer=lambda *_: (_ for _ in ()).throw(AssertionError("import called")),
    )

    assert code == 0
    assert report["status"] == "READY_TO_IMPORT"
    assert report["history_mutated"] is False
    assert report["backup"] is None


def test_stale_confirmation_blocks_before_backup(tmp_path, monkeypatch):
    history = tmp_path / "history.duckdb"
    history.write_bytes(b"history")
    monkeypatch.setattr(module, "audit_input_fingerprint", lambda **kwargs: "new")

    report, code = module.import_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=history,
        apply=True,
        expected_input_fingerprint="old",
        readiness_discoverer=lambda **kwargs: {CONTEXT: ready_row(tmp_path)},
        backupper=lambda *_: (_ for _ in ()).throw(AssertionError("backup called")),
    )

    assert code == 2
    assert report["status"] == "BLOCKED_STALE_READINESS"
    assert report["history_mutated"] is False


def test_apply_backs_up_then_imports_and_post_validates(tmp_path, monkeypatch):
    history = tmp_path / "history.duckdb"
    history.write_bytes(b"history")
    row = ready_row(tmp_path)
    calls = []
    discoveries = iter(({CONTEXT: row}, {CONTEXT: {"status": H3_IMPORTED}}))
    monkeypatch.setattr(module, "audit_input_fingerprint", lambda **kwargs: "fresh")

    def backupper(db, root):
        calls.append(("backup", db, root))
        return {"path": str(root / "backup.duckdb"), "verified": True, "sha256": "a" * 64}

    def importer(db, patterns, matches):
        calls.append(("import", db, patterns, matches))
        return {"status": "RUN", "pattern_run_id": 7}

    report, code = module.import_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=history,
        backup_root=tmp_path / "backups",
        apply=True,
        expected_input_fingerprint="fresh",
        readiness_discoverer=lambda **kwargs: next(discoveries),
        backupper=backupper,
        importer=importer,
    )

    assert code == 0
    assert [call[0] for call in calls] == ["backup", "import"]
    assert report["status"] == "IMPORTED"
    assert report["history_mutated"] is True
    assert report["backup"]["verified"] is True


def test_unverified_backup_fails_closed_without_import(tmp_path, monkeypatch):
    history = tmp_path / "history.duckdb"
    history.write_bytes(b"history")
    monkeypatch.setattr(module, "audit_input_fingerprint", lambda **kwargs: "fresh")

    report, code = module.import_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=history,
        apply=True,
        readiness_discoverer=lambda **kwargs: {CONTEXT: ready_row(tmp_path)},
        backupper=lambda *_: {"verified": False},
        importer=lambda *_: (_ for _ in ()).throw(AssertionError("import called")),
    )

    assert code == 1
    assert report["status"] == "FAILED"
    assert report["history_mutated"] is False


def test_backup_history_database_checkpoints_and_verifies_real_duckdb(tmp_path):
    import duckdb

    history = tmp_path / "history.duckdb"
    connection = duckdb.connect(str(history))
    connection.execute("CREATE TABLE sample(value INTEGER)")
    connection.execute("INSERT INTO sample VALUES (42)")
    connection.close()

    backup = module.backup_history_database(history, tmp_path / "backups")

    assert backup["verified"] is True
    assert backup["sha256"] == module.sha256_file(history)
    restored = duckdb.connect(backup["path"], read_only=True)
    try:
        assert restored.execute("SELECT value FROM sample").fetchone() == (42,)
    finally:
        restored.close()
