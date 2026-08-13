# client/tests/test_identity.py
import subprocess

import pytest

from agent_mesh_client.identity import build_identity, compute_agent_id


def test_compute_agent_id_is_deterministic():
    a1 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj", "backend")
    a2 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj", "backend")
    assert a1 == a2
    assert a1.startswith("agent-")


def test_compute_agent_id_differs_by_workspace():
    a1 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj-a", "backend")
    a2 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj-b", "backend")
    assert a1 != a2


def test_compute_agent_id_differs_by_role():
    a1 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj", "backend")
    a2 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj", "frontend")
    assert a1 != a2


def test_build_identity_requires_role_when_none_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path / "home"))
    with pytest.raises(ValueError):
        build_identity(cwd=str(tmp_path))


def test_build_identity_saves_role_then_reuses_it(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path / "home"))

    first = build_identity(role="backend", display_name="BE-01", cwd=str(tmp_path))
    assert first["role"] == "backend"
    assert first["display_name"] == "BE-01"

    second = build_identity(cwd=str(tmp_path))  # no role passed this time
    assert second["agent_id"] == first["agent_id"]
    assert second["role"] == "backend"
    assert second["display_name"] == "BE-01"


def test_build_identity_project_defaults_to_workspace_when_never_declared(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path / "home"))

    identity = build_identity(role="backend", cwd=str(tmp_path))

    assert identity["project"] == identity["workspace"]


def test_build_identity_uses_explicit_project_and_persists_it(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path / "home"))

    first = build_identity(role="backend", project="javis-core", cwd=str(tmp_path))
    assert first["project"] == "javis-core"

    second = build_identity(cwd=str(tmp_path))  # no role/project passed this time
    assert second["project"] == "javis-core"


def test_build_identity_second_call_without_project_reuses_saved_project(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path / "home"))

    build_identity(role="backend", project="javis-core", cwd=str(tmp_path))
    second = build_identity(role="backend", cwd=str(tmp_path))  # role passed again, no project

    assert second["project"] == "javis-core"


def test_build_identity_uses_git_root(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    nested = repo / "src" / "sub"
    nested.mkdir(parents=True)

    identity = build_identity(role="backend", cwd=str(nested))

    assert identity["workspace"] == str(repo.resolve())
    assert identity["agent_id"].startswith("agent-")
