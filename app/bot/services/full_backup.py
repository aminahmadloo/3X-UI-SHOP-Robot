from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from redis.asyncio import Redis

from app.bot.services.full_backup_storage import BackupStorageConfig, S3CompatibleBackupStorage
from app.config import Config

logger = logging.getLogger(__name__)

BACKUP_PART_BYTES = 49_000_000
TELEGRAM_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
BACKUP_MAX_TOTAL_BYTES = 5 * 1024 * 1024 * 1024
BACKUP_ROOT = Path("/tmp/toonelvpn-full-backups")


@dataclass(frozen=True)
class FullBackupResult:
    path: Path
    parts: tuple[Path, ...]
    size_bytes: int
    sha256: str
    redis_keys: int
    source_app_path: str
    delivery: str
    download_url: str | None = None
    storage_key: str | None = None


def _copy_sqlite_consistent(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db)
            destination_db.commit()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _split_file(source: Path, part_size: int) -> tuple[Path, ...]:
    parts: list[Path] = []
    with source.open("rb") as handle:
        index = 1
        while True:
            chunk = handle.read(part_size)
            if not chunk:
                break
            part = source.with_name(f"{source.name}.part{index:03d}")
            part.write_bytes(chunk)
            parts.append(part)
            index += 1
    return tuple(parts)


async def _dump_redis(redis_url: str, destination: Path) -> int:
    redis = Redis.from_url(redis_url, decode_responses=False)
    count = 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            async for key in redis.scan_iter(count=500):
                value = await redis.dump(key)
                if value is None:
                    continue
                ttl = await redis.pttl(key)
                record = {
                    "key": base64.b64encode(key).decode("ascii"),
                    "payload": base64.b64encode(value).decode("ascii"),
                    "pttl": ttl,
                }
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                count += 1
    finally:
        await redis.aclose()
    return count


def _build_archive(work_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, mode="w:gz", compresslevel=6) as archive:
        archive.add(work_dir / "app", arcname="app", recursive=True)
        archive.add(work_dir / "database", arcname="database", recursive=True)
        archive.add(work_dir / "redis", arcname="redis", recursive=True)
        archive.add(work_dir / "config", arcname="config", recursive=True)
        archive.add(work_dir / "MANIFEST.json", arcname="MANIFEST.json")
        archive.add(work_dir / "RESTORE.md", arcname="RESTORE.md")


def _storage_key(storage: BackupStorageConfig, timestamp: str) -> str:
    prefix = storage.prefix.strip("/")
    suffix = f"{timestamp}-{uuid.uuid4().hex}.tar.gz"
    return f"{prefix}/{suffix}" if prefix else suffix


async def create_full_backup(config: Config) -> FullBackupResult:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"toonelvpn-{timestamp}-", dir=BACKUP_ROOT))
    archive_path = BACKUP_ROOT / f"toonelvpn-full-backup-{timestamp}.tar.gz"
    parts: tuple[Path, ...] = ()

    app_path = Path("/app")
    db_path = Path("/app/data") / f"{config.database.NAME}.sqlite3"

    try:
        for directory in ("app", "database", "redis", "config"):
            (work_dir / directory).mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            shutil.copytree,
            app_path,
            work_dir / "app",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                ".env", "__pycache__", "*.pyc", "*.pyo", "logs"
            ),
        )

        if db_path.exists():
            await asyncio.to_thread(
                _copy_sqlite_consistent,
                db_path,
                work_dir / "database" / db_path.name,
            )

        redis_keys = await _dump_redis(config.redis.url(), work_dir / "redis" / "dump.jsonl")

        env_path = app_path / ".env"
        if env_path.exists():
            await asyncio.to_thread(shutil.copy2, env_path, work_dir / "config" / ".env")

        manifest = {
            "format": "toonelvpn-full-backup-v2",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hostname": os.uname().nodename,
            "application_root": str(app_path),
            "database": db_path.name if db_path.exists() else None,
            "redis_database": config.redis.DB_NAME,
            "redis_keys": redis_keys,
            "included": [
                "deployed /app application tree",
                "consistent SQLite database copy",
                "runtime data and locales",
                "logical Redis dump with TTL metadata",
                "runtime .env configuration",
            ],
            "excluded_from_app": [".env", "__pycache__", "*.pyc", "*.pyo", "logs"],
            "telegram_upload_part_limit_bytes": BACKUP_PART_BYTES,
            "telegram_fallback_total_limit_bytes": TELEGRAM_MAX_TOTAL_BYTES,
            "external_storage_total_limit_bytes": BACKUP_MAX_TOTAL_BYTES,
            "transport_policy": "direct Telegram <=49MB; B2 presigned download link when configured; Telegram parts as fallback up to 1GiB",
            "note": "The deployed /app tree is the application snapshot. Git repository metadata is intentionally not copied into the container backup.",
        }
        _write_json(work_dir / "MANIFEST.json", manifest)

        (work_dir / "RESTORE.md").write_text(
            "# ToonelVPN Full Backup Restore\n\n"
            "This archive contains the deployed application tree, a consistent SQLite copy, "
            "a logical Redis dump, and the runtime .env file.\n\n"
            "For Telegram multipart delivery, concatenate all `.partNNN` files in numeric order "
            "before extraction. B2 delivery provides the original `.tar.gz` as a single downloadable file.\n\n"
            "`cat toonelvpn-full-backup-*.tar.gz.part* > toonelvpn-full-backup.tar.gz`\n\n"
            "Verify the resulting archive SHA-256 against the value reported by the bot.\n\n"
            "1. Deploy the matching ToonelVPN source revision from the Git repository.\n"
            "2. Stop the bot container before replacing runtime data.\n"
            "3. Restore `database/*.sqlite3` into `app/data/`.\n"
            "4. Restore archived runtime files from `app/data/` and `app/locales/` as required.\n"
            "5. Restore `config/.env` to the bot runtime environment.\n"
            "6. Restore Redis using `redis/dump.jsonl`: base64-decode `key` and `payload`, "
            "then issue Redis RESTORE with the recorded `pttl` (use 0 for persistent keys).\n"
            "7. Rebuild and recreate the bot container.\n\n"
            "Never commit `config/.env` or this archive to Git.\n",
            encoding="utf-8",
        )

        await asyncio.to_thread(_build_archive, work_dir, archive_path)
        size_bytes = archive_path.stat().st_size
        if size_bytes > BACKUP_MAX_TOTAL_BYTES:
            raise ValueError(
                f"Backup size is {size_bytes / (1024 * 1024):.1f} MB; "
                f"the configured maximum is {BACKUP_MAX_TOTAL_BYTES / (1024 * 1024 * 1024):.0f} GiB."
            )
        sha256 = await asyncio.to_thread(_sha256, archive_path)

        if size_bytes <= BACKUP_PART_BYTES:
            parts = (archive_path,)
            return FullBackupResult(
                path=archive_path,
                parts=parts,
                size_bytes=size_bytes,
                sha256=sha256,
                redis_keys=redis_keys,
                source_app_path=str(app_path),
                delivery="telegram",
            )

        storage = BackupStorageConfig.from_env()
        if storage.enabled:
            storage_client = S3CompatibleBackupStorage(storage)
            uploaded = await storage_client.upload(
                archive_path, _storage_key(storage, timestamp)
            )
            return FullBackupResult(
                path=archive_path,
                parts=(),
                size_bytes=size_bytes,
                sha256=sha256,
                redis_keys=redis_keys,
                source_app_path=str(app_path),
                delivery="download_link",
                download_url=uploaded.url,
                storage_key=uploaded.key,
            )

        if size_bytes > TELEGRAM_MAX_TOTAL_BYTES:
            raise ValueError(
                "Backup is larger than 1 GiB and external backup storage is not configured. "
                "Configure FULL_BACKUP_STORAGE_* to receive a single download link."
            )

        parts = await asyncio.to_thread(_split_file, archive_path, BACKUP_PART_BYTES)
        return FullBackupResult(
            path=archive_path,
            parts=parts,
            size_bytes=size_bytes,
            sha256=sha256,
            redis_keys=redis_keys,
            source_app_path=str(app_path),
            delivery="telegram_parts",
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        for part in parts:
            if part != archive_path:
                part.unlink(missing_ok=True)
        raise
    finally:
        await asyncio.to_thread(shutil.rmtree, work_dir, True)


async def cleanup_full_backup(path: Path, parts: tuple[Path, ...] = ()) -> None:
    await asyncio.to_thread(path.unlink, True)
    for part in parts:
        if part != path:
            await asyncio.to_thread(part.unlink, True)
