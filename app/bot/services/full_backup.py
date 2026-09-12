from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from redis.asyncio import Redis

from app.config import Config

logger = logging.getLogger(__name__)

BACKUP_MAX_UPLOAD_BYTES = 48 * 1024 * 1024
BACKUP_ROOT = Path("/tmp/toonelvpn-full-backups")


@dataclass(frozen=True)
class FullBackupResult:
    path: Path
    size_bytes: int
    sha256: str
    redis_keys: int
    source_app_path: str


def _copy_sqlite_consistent(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db)
            destination_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination_db.commit()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


async def create_full_backup(config: Config) -> FullBackupResult:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"toonelvpn-{timestamp}-", dir=BACKUP_ROOT))
    archive_path = BACKUP_ROOT / f"toonelvpn-full-backup-{timestamp}.tar.gz"

    app_path = Path("/app")
    db_path = Path(config.database.url().replace("sqlite+aiosqlite:", ""))

    try:
        (work_dir / "app").mkdir(parents=True, exist_ok=True)
        (work_dir / "database").mkdir(parents=True, exist_ok=True)
        (work_dir / "redis").mkdir(parents=True, exist_ok=True)
        (work_dir / "config").mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(
            lambda: __import__("shutil").copytree(
                app_path,
                work_dir / "app",
                dirs_exist_ok=True,
                ignore=__import__("shutil").ignore_patterns("__pycache__", "*.pyc", "*.pyo", "logs"),
            )
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
            await asyncio.to_thread(
                __import__("shutil").copy2,
                env_path,
                work_dir / "config" / ".env",
            )

        manifest = {
            "format": "toonelvpn-full-backup-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hostname": os.uname().nodename,
            "application_root": str(app_path),
            "database": db_path.name if db_path.exists() else None,
            "redis_database": config.redis.DB_NAME,
            "redis_keys": redis_keys,
            "excluded_from_app": ["__pycache__", "*.pyc", "*.pyo", "logs"],
            "telegram_upload_limit_bytes": BACKUP_MAX_UPLOAD_BYTES,
            "note": "Application source is captured from the deployed /app tree; repository metadata is intentionally not copied into the container backup.",
        }
        _write_json(work_dir / "MANIFEST.json", manifest)

        (work_dir / "RESTORE.md").write_text(
            "# ToonelVPN Full Backup Restore\n\n"
            "This archive contains the deployed application tree, a consistent SQLite copy, "
            "a logical Redis dump, and the runtime .env file.\n\n"
            "1. Deploy the matching ToonelVPN source revision from the Git repository.\n"
            "2. Stop the bot container before replacing runtime data.\n"
            "3. Restore `database/*.sqlite3` into `app/data/`.\n"
            "4. Restore the archived `app/data/`, `app/locales/`, and `config/.env` as required.\n"
            "5. Restore Redis using the records in `redis/dump.jsonl` with the Redis DUMP/RESTORE commands.\n"
            "6. Rebuild and recreate the bot container.\n\n"
            "Never commit `config/.env` or this archive to Git.\n",
            encoding="utf-8",
        )

        await asyncio.to_thread(_build_archive, work_dir, archive_path)
        size_bytes = archive_path.stat().st_size
        sha256 = await asyncio.to_thread(_sha256, archive_path)

        if size_bytes > BACKUP_MAX_UPLOAD_BYTES:
            raise ValueError(
                f"Backup size is {size_bytes / (1024 * 1024):.1f} MB; "
                f"Telegram upload limit configured for this feature is {BACKUP_MAX_UPLOAD_BYTES / (1024 * 1024):.0f} MB."
            )

        return FullBackupResult(
            path=archive_path,
            size_bytes=size_bytes,
            sha256=sha256,
            redis_keys=redis_keys,
            source_app_path=str(app_path),
        )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        await asyncio.to_thread(__import__("shutil").rmtree, work_dir, True)


async def cleanup_full_backup(path: Path) -> None:
    await asyncio.to_thread(path.unlink, True)
