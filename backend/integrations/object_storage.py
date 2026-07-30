"""MinIO/S3 object storage wrapper. All boto3 error types stop here."""
import logging
import threading
from typing import Any, BinaryIO, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from core.config import Settings
from core.exceptions import ObjectNotFoundError, ObjectStorageError

logger = logging.getLogger(__name__)


class MinIOObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.bucket = settings.minio_bucket
        self._client: Optional[Any] = None
        self._lock = threading.Lock()

    def _s3(self) -> Any:
        # boto3 client creation is offline; kept lazy for symmetry/testability.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = boto3.client(
                        "s3",
                        endpoint_url=f"http://{self._settings.minio_endpoint}",
                        aws_access_key_id=self._settings.minio_access_key,
                        aws_secret_access_key=self._settings.minio_secret_key,
                        config=Config(
                            # Default pool (10) is smaller than the request
                            # threadpool, so concurrent uploads queued invisibly.
                            max_pool_connections=self._settings.s3_max_pool_connections,
                            connect_timeout=self._settings.s3_connect_timeout,
                            read_timeout=self._settings.s3_read_timeout,
                            # Bounded retries: a hung MinIO must surface as an
                            # error, not hold a worker thread for minutes.
                            retries={"max_attempts": 3, "mode": "standard"},
                        ),
                    )
        return self._client

    def ensure_bucket(self) -> None:
        try:
            self._s3().head_bucket(Bucket=self.bucket)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                logger.info(f"Bucket '{self.bucket}' does not exist, creating...")
                try:
                    self._s3().create_bucket(Bucket=self.bucket)
                except Exception as inner:
                    raise ObjectStorageError("Failed to create bucket", detail=str(inner)) from inner
            else:
                raise ObjectStorageError("Failed to reach MinIO", detail=str(e)) from e

    def head_etag(self, bucket: str, key: str) -> str:
        try:
            head = self._s3().head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                raise ObjectNotFoundError(f"Object '{key}' not found in bucket '{bucket}'.") from e
            raise ObjectStorageError("Failed to stat object", detail=str(e)) from e
        return str(head.get("ETag", "")).strip('"')

    def upload_fileobj(self, fileobj: BinaryIO, key: str) -> None:
        try:
            self._s3().upload_fileobj(fileobj, self.bucket, key)
        except Exception as e:
            raise ObjectStorageError("Failed to upload to MinIO", detail=str(e)) from e

    def download_file(self, bucket: str, key: str, local_path: str) -> None:
        try:
            self._s3().download_file(bucket, key, local_path)
        except Exception as e:
            raise ObjectStorageError("Failed to download from MinIO", detail=str(e)) from e

    def delete_object(self, key: str) -> None:
        try:
            self._s3().delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            raise ObjectStorageError(f"Failed to delete '{key}'", detail=str(e)) from e

    def list_keys(self) -> list[str]:
        """All object keys in the bucket.

        Paginated: a bare list_objects_v2 caps at 1000 keys, which silently
        truncated the document list (and the UI's source filter) once the
        corpus grew past that.
        """
        keys: list[str] = []
        try:
            paginator = self._s3().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket):
                keys.extend(item["Key"] for item in page.get("Contents", []))
        except Exception as e:
            raise ObjectStorageError("Could not list documents from MinIO", detail=str(e)) from e
        return keys
