from agent_mesh_client import config


def test_save_and_get_role_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))

    assert config.get_role("/home/anh/proj") is None

    config.save_role("/home/anh/proj", "backend", display_name="BE-01", domain="auth")

    saved = config.get_role("/home/anh/proj")
    assert saved == {"role": "backend", "display_name": "BE-01", "domain": "auth", "project": None}


def test_save_role_does_not_clobber_other_workspaces(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))

    config.save_role("/home/anh/proj-a", "backend")
    config.save_role("/home/anh/proj-b", "frontend")

    assert config.get_role("/home/anh/proj-a")["role"] == "backend"
    assert config.get_role("/home/anh/proj-b")["role"] == "frontend"


def test_role_file_is_private(monkeypatch, tmp_path):
    import os
    import stat

    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    config.save_role("/home/anh/proj", "backend")

    role_file = tmp_path / "roles.json"
    assert stat.S_IMODE(os.stat(role_file).st_mode) & 0o777 == 0o600


def test_save_role_preserves_display_name_when_omitted_on_later_call(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))

    config.save_role("/home/anh/proj", "backend", display_name="Anh")
    config.save_role("/home/anh/proj", "backend", display_name="")

    assert config.get_role("/home/anh/proj")["display_name"] == "Anh"


def test_save_role_stores_and_returns_project(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))

    config.save_role("/home/anh/proj", "backend", project="javis-ai")

    assert config.get_role("/home/anh/proj")["project"] == "javis-ai"
