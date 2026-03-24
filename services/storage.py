"""
Storage abstraction layer — supports local filesystem and S3.
ChromaDB always uses local filesystem (needs direct path access).
"""
import shutil
import logging
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Optional

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract interface for file storage operations."""

    @abstractmethod
    def save(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def save_fileobj(self, key: str, fileobj: BinaryIO) -> str: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    def local_path(self, key: str) -> Optional[Path]:
        """Return local path for tools that need filesystem access (PyMuPDF, Tesseract).
        For S3, downloads to a local cache first."""
        ...


class LocalStorage(StorageBackend):
    """Stores files on the local filesystem under a base directory."""

    def __init__(self, base_dir: str = "user_sessions"):
        self.base = Path(base_dir)

    def _resolve(self, key: str) -> Path:
        p = self.base / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.write_bytes(data)
        return str(path)

    def save_fileobj(self, key: str, fileobj: BinaryIO) -> str:
        path = self._resolve(key)
        with path.open("wb") as f:
            shutil.copyfileobj(fileobj, f)
        return str(path)

    def read(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        p = self._resolve(key)
        if p.exists():
            p.unlink()

    def delete_prefix(self, prefix: str) -> None:
        d = self.base / prefix
        if d.exists() and d.is_dir():
            shutil.rmtree(d)

    def local_path(self, key: str) -> Optional[Path]:
        p = self._resolve(key)
        return p if p.exists() else None


class S3Storage(StorageBackend):
    """Stores files in an S3-compatible bucket with local caching for filesystem tools."""

    def __init__(self, bucket: str, region: str, access_key: str, secret_key: str):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self._local_cache = Path("/tmp/s3_cache")
        self._local_cache.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        self.s3.upload_fileobj(BytesIO(data), self.bucket, key)
        # Also write to local cache so subsequent local_path() calls don't need a download
        local = self._local_cache / key
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return f"s3://{self.bucket}/{key}"

    def save_fileobj(self, key: str, fileobj: BinaryIO) -> str:
        # Read into memory to write both to S3 and local cache
        data = fileobj.read()
        return self.save(key, data)

    def read(self, key: str) -> bytes:
        buf = BytesIO()
        self.s3.download_fileobj(self.bucket, key, buf)
        return buf.getvalue()

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=key)
        # Clean local cache
        local = self._local_cache / key
        if local.exists():
            local.unlink()

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            if "Contents" in page:
                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
        # Clean local cache
        local_dir = self._local_cache / prefix
        if local_dir.exists() and local_dir.is_dir():
            shutil.rmtree(local_dir)

    def local_path(self, key: str) -> Optional[Path]:
        """Download to local cache for PyMuPDF/Tesseract access."""
        local = self._local_cache / key
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.s3.download_file(self.bucket, key, str(local))
            except Exception as e:
                logger.error(f"Failed to download s3://{self.bucket}/{key}: {e}")
                return None
        return local


# --- Singleton ---

_storage_instance: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """Returns the configured storage backend (cached singleton)."""
    global _storage_instance
    if _storage_instance is None:
        from config import settings
        if settings.STORAGE_BACKEND == "s3" and settings.S3_BUCKET:
            _storage_instance = S3Storage(
                bucket=settings.S3_BUCKET,
                region=settings.S3_REGION,
                access_key=settings.S3_ACCESS_KEY,
                secret_key=settings.S3_SECRET_KEY,
            )
            logger.info(f"Using S3 storage: {settings.S3_BUCKET}")
        else:
            _storage_instance = LocalStorage(settings.USER_SESSIONS_DIR)
            logger.info("Using local file storage")
    return _storage_instance
