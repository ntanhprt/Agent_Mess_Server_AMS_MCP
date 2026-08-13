import os
from typing import Any

import boto3
from botocore.client import Config as BotoConfig

from . import config

BUCKET = "agent-mesh"


def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=config.minio_endpoint(),
        aws_access_key_id=config.minio_access_key(),
        aws_secret_access_key=config.minio_secret_key(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _ensure_bucket(client: Any) -> None:
    existing = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    if BUCKET not in existing:
        client.create_bucket(Bucket=BUCKET)


def upload_artifact(path: str, task_id: str) -> str:
    client = _client()
    _ensure_bucket(client)
    filename = os.path.basename(path)
    object_key = f"{task_id}/{filename}"
    client.upload_file(path, BUCKET, object_key)
    return object_key


def download_artifact(object_key: str, dest_path: str) -> None:
    client = _client()
    client.download_file(BUCKET, object_key, dest_path)
