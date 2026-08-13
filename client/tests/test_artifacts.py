from unittest.mock import MagicMock

from agent_mesh_client import artifacts


def test_upload_artifact_uses_task_id_and_filename_as_key(monkeypatch, tmp_path):
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = {"Buckets": [{"Name": "agent-mesh"}]}
    monkeypatch.setattr(artifacts, "_client", lambda: fake_client)

    src = tmp_path / "spec.md"
    src.write_text("hello")

    key = artifacts.upload_artifact(str(src), "task-123")

    assert key == "task-123/spec.md"
    fake_client.upload_file.assert_called_once_with(str(src), "agent-mesh", "task-123/spec.md")


def test_upload_artifact_creates_bucket_if_missing(monkeypatch, tmp_path):
    fake_client = MagicMock()
    fake_client.list_buckets.return_value = {"Buckets": []}
    monkeypatch.setattr(artifacts, "_client", lambda: fake_client)

    src = tmp_path / "spec.md"
    src.write_text("hello")

    artifacts.upload_artifact(str(src), "task-123")

    fake_client.create_bucket.assert_called_once_with(Bucket="agent-mesh")


def test_download_artifact_fetches_by_key(monkeypatch, tmp_path):
    fake_client = MagicMock()
    monkeypatch.setattr(artifacts, "_client", lambda: fake_client)

    dest = str(tmp_path / "out.md")
    artifacts.download_artifact("task-123/spec.md", dest)

    fake_client.download_file.assert_called_once_with("agent-mesh", "task-123/spec.md", dest)
