import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from search_ir_dev_fixtures import make_candidate
from search_ir import provenance


def record(path, data):
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def test_current_matching_source_does_not_need_git(tmp_path, monkeypatch):
    path = tmp_path / "module.py"
    path.write_bytes(b"same")
    monkeypatch.setattr(provenance.subprocess, "run", lambda *a, **k: pytest.fail("unexpected git lookup"))
    assert provenance.verify_source_record(record(path, b"same"), root=tmp_path)["verified_via"] == "current-file"


def test_changed_live_source_requires_exact_archived_bytes(tmp_path, monkeypatch):
    path = tmp_path / "module.py"
    path.write_bytes(b"new")
    calls = []
    def show(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b"old")
    monkeypatch.setattr(provenance.subprocess, "run", show)
    value = provenance.verify_source_record(record(path, b"old"), root=tmp_path)
    assert value["verified_via"] == "git:834d449:module.py"
    assert calls == [["git", "show", "834d449:module.py"]]


def test_unverifiable_source_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "module.py"
    path.write_bytes(b"new")
    monkeypatch.setattr(provenance.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"wrong"))
    with pytest.raises(provenance.ProvenanceError, match="无法"):
        provenance.verify_source_record(record(path, b"old"), root=tmp_path)


def test_archive_does_not_accept_option_injection(tmp_path):
    path = tmp_path / "module.py"
    path.write_bytes(b"new")
    with pytest.raises(provenance.ProvenanceError, match="提交ID"):
        provenance.verify_source_record(record(path, b"old"), root=tmp_path, checkpoint="--output=bad")
