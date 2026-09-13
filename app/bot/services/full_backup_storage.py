from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import os
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BackupStorageConfig:
    enabled: bool
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str
    url_expires_seconds: int
    prefix: str

    @classmethod
    def from_env(cls) -> "BackupStorageConfig":
        return cls(
            enabled=os.getenv("FULL_BACKUP_STORAGE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            endpoint=os.getenv("FULL_BACKUP_STORAGE_ENDPOINT", "").strip().rstrip("/"),
            bucket=os.getenv("FULL_BACKUP_STORAGE_BUCKET", "").strip(),
            access_key_id=os.getenv("FULL_BACKUP_STORAGE_ACCESS_KEY_ID", "").strip(),
            secret_access_key=os.getenv("FULL_BACKUP_STORAGE_SECRET_ACCESS_KEY", ""),
            region=os.getenv("FULL_BACKUP_STORAGE_REGION", "us-west-004").strip() or "us-west-004",
            url_expires_seconds=int(os.getenv("FULL_BACKUP_STORAGE_URL_EXPIRES_SECONDS", "86400")),
            prefix=os.getenv("FULL_BACKUP_STORAGE_PREFIX", "toonelvpn/full-backups").strip().strip("/"),
        )


@dataclass(frozen=True)
class UploadedBackup:
    key: str
    url: str
    size_bytes: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _aws_encode(value: str, safe: str = "-_.~") -> str:
    return urllib.parse.quote(value, safe=safe)


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(f"{_aws_encode(key)}={_aws_encode(value)}" for key, value in sorted(params.items()))


def _canonical_target(endpoint: str, bucket: str, key: str) -> tuple[urllib.parse.SplitResult, str, str]:
    parsed = urllib.parse.urlsplit(endpoint.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("FULL_BACKUP_STORAGE_ENDPOINT must be a valid http(s) URL")
    base_path = parsed.path.rstrip("/")
    encoded_key = "/".join(_aws_encode(part) for part in key.split("/"))
    canonical_uri = f"{base_path}/{_aws_encode(bucket)}"
    if encoded_key:
        canonical_uri += f"/{encoded_key}"
    return parsed, canonical_uri, f"{parsed.scheme}://{parsed.netloc}{canonical_uri}"


def _signing_key(secret: str, date_stamp: str, region: str) -> bytes:
    k_date = _hmac(("AWS4" + secret).encode(), date_stamp)
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


class S3CompatibleBackupStorage:
    """Minimal stdlib-only S3 client for the large-backup path.

    Backblaze B2 exposes an S3-compatible API, so the bot image needs no SDK dependency.
    """

    MAX_SINGLE_PUT_BYTES = 5 * 1024 * 1024 * 1024

    def __init__(self, config: BackupStorageConfig) -> None:
        self.config = config
        if not config.enabled:
            raise ValueError("External backup storage is disabled")
        if not all((config.endpoint, config.bucket, config.access_key_id, config.secret_access_key)):
            raise ValueError("External backup storage configuration is incomplete")
        if not 1 <= config.url_expires_seconds <= 604800:
            raise ValueError("FULL_BACKUP_STORAGE_URL_EXPIRES_SECONDS must be between 1 and 604800")

    def _presigned_get_url(self, key: str) -> str:
        parsed, canonical_uri, base_url = _canonical_target(self.config.endpoint, self.config.bucket, key)
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        query = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.config.access_key_id}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(self.config.url_expires_seconds),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_request = "\n".join(("GET", canonical_uri, _canonical_query(query), f"host:{parsed.netloc}\n", "host", "UNSIGNED-PAYLOAD"))
        string_to_sign = "\n".join(("AWS4-HMAC-SHA256", amz_date, credential_scope, hashlib.sha256(canonical_request.encode()).hexdigest()))
        signature = hmac.new(_signing_key(self.config.secret_access_key, date_stamp, self.config.region), string_to_sign.encode(), hashlib.sha256).hexdigest()
        query["X-Amz-Signature"] = signature
        return f"{base_url}?{_canonical_query(query)}"

    def _put_object(self, key: str, path: Path) -> None:
        size = path.stat().st_size
        if size > self.MAX_SINGLE_PUT_BYTES:
            raise ValueError("Backup exceeds the 5 GiB external storage limit supported by this implementation.")

        payload_hash = _sha256_file(path)
        parsed, canonical_uri, _ = _canonical_target(self.config.endpoint, self.config.bucket, key)
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        credential_scope = f"{date_stamp}/{self.config.region}/s3/aws4_request"
        headers = {
            "host": parsed.netloc,
            "content-length": str(size),
            "content-type": "application/gzip",
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        signed_headers = ";".join(sorted(headers))
        canonical_request = "\n".join(("PUT", canonical_uri, "", canonical_headers, signed_headers, payload_hash))
        string_to_sign = "\n".join(("AWS4-HMAC-SHA256", amz_date, credential_scope, hashlib.sha256(canonical_request.encode()).hexdigest()))
        signature = hmac.new(_signing_key(self.config.secret_access_key, date_stamp, self.config.region), string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.config.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_class(parsed.netloc, timeout=300)
        try:
            connection.putrequest("PUT", canonical_uri)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    connection.send(chunk)
            response = connection.getresponse()
            response_body = response.read(4096).decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"External backup upload failed ({response.status}): {response_body[:1000]}")
        finally:
            connection.close()

    async def upload(self, path: Path, key: str) -> UploadedBackup:
        size = path.stat().st_size
        await asyncio.to_thread(self._put_object, key, path)
        return UploadedBackup(key=key, url=self._presigned_get_url(key), size_bytes=size)
