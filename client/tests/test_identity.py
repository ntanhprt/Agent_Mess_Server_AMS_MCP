import subprocess

from agent_mesh_client.identity import build_identity, compute_agent_id


def test_compute_agent_id_is_deterministic():
    a1 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj")
    a2 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj")
    assert a1 == a2
    assert a1.startswith("agent-")


def test_compute_agent_id_differs_by_workspace():
    a1 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj-a")
    a2 = compute_agent_id("anh", "DEV-PC-01", "/home/anh/proj-b")
    assert a1 != a2


def test_build_identity_uses_git_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    nested = repo / "src" / "sub"
    nested.mkdir(parents=True)

    identity = build_identity(cwd=str(nested))

    assert identity["workspace"] == str(repo.resolve())
    assert identity["agent_id"].startswith("agent-")
