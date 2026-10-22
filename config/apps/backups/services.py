import hashlib
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from uuid import uuid4
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.utils import timezone

from .models import BackupRecord, BackupSettings

RETENTION_COUNT = 5
BACKUP_VERSION = 1
STALE_BACKUP_HOURS = 24

def backup_root():
    root = Path(os.environ.get("BACKUP_ROOT", settings.BASE_DIR / "data" / "backups"))
    root.mkdir(parents=True, exist_ok=True)
    return root

def _run(command, *, env=None):
    return subprocess.run(command, check=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def _dump_database(destination):
    config = connections["default"].settings_dict
    engine = config["ENGINE"]
    if engine.endswith("sqlite3"):
        source = Path(config["NAME"])
        if not source.exists():
            raise RuntimeError(f"SQLite database does not exist: {source}")
        source_conn = sqlite3.connect(str(source))
        destination_conn = sqlite3.connect(str(destination))
        try:
            source_conn.backup(destination_conn)
        finally:
            destination_conn.close()
            source_conn.close()
        return "sqlite-online-backup"
    if engine.endswith("postgresql"):
        env = os.environ.copy()
        if config.get("PASSWORD"):
            env["PGPASSWORD"] = str(config["PASSWORD"])
        _run([
            "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
            "--host", str(config.get("HOST") or "127.0.0.1"),
            "--port", str(config.get("PORT") or "5432"),
            "--username", str(config.get("USER") or ""),
            "--file", str(destination),
            str(config.get("NAME") or ""),
        ], env=env)
        return "postgresql-pgdump"
    raise RuntimeError(f"Unsupported database engine for backup: {engine}")

def _copy_tree(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.exists():
        return
    shutil.copytree(
        source, destination, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".pytest_cache", ".mypy_cache", "backups", "logs"),
    )

def _backup_lock_path():
    root = backup_root()
    return root / ".backup.lock"

@contextmanager
def backup_lock():
    """Prevent concurrent backups across web, Celery and systemd processes."""
    lock_path = _backup_lock_path()
    lock_path.touch(exist_ok=True)
    lock_file = None
    cache_acquired = False
    try:
        # On Linux the file lock is the reliable same-host guard. On Windows
        # development environments, fall back to the configured cache lock.
        try:
            import fcntl
        except ImportError:
            fcntl = None

        if fcntl is not None:
            lock_file = open(lock_path, "r+")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return

        try:
            cache_acquired = cache.add("babaei:backup:lock", uuid4().hex, timeout=6 * 60 * 60)
        except Exception:
            cache_acquired = True

        if not cache_acquired:
            yield False
            return

        yield True
    finally:
        if cache_acquired:
            try:
                cache.delete("babaei:backup:lock")
            except Exception:
                pass
        if lock_file is not None:
            try:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            lock_file.close()

def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _encrypt(source, destination):
    key = os.environ.get("BACKUP_ENCRYPTION_KEY", "").strip()
    if not key:
        shutil.move(source, destination)
        return False
    _run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", str(source), "-out", str(destination), "-pass", f"pass:{key}"])
    Path(source).unlink(missing_ok=True)
    return True

def _s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("BACKUP_S3_ENDPOINT") or None,
        aws_access_key_id=os.environ.get("BACKUP_S3_ACCESS_KEY") or None,
        aws_secret_access_key=os.environ.get("BACKUP_S3_SECRET_KEY") or None,
        region_name=os.environ.get("BACKUP_S3_REGION") or None,
    )

def _upload_remote(path, key):
    bucket = os.environ.get("BACKUP_S3_BUCKET", "").strip()
    if not bucket:
        return "", "local"
    try:
        client = _s3_client()
    except ImportError as exc:
        raise RuntimeError("S3 storage is configured but boto3 is not installed.") from exc
    client.upload_file(str(path), bucket, key)
    return key, "s3"

def _delete_remote(record):
    if record.storage_backend != "s3" or not record.remote_key:
        return
    bucket = os.environ.get("BACKUP_S3_BUCKET", "").strip()
    if not bucket:
        return
    try:
        _s3_client().delete_object(Bucket=bucket, Key=record.remote_key)
    except Exception:
        pass

def recover_stale_backups(now=None):
    """Mark abandoned RUNNING records as failed after a generous timeout."""
    now = now or timezone.now()
    cutoff = now - timedelta(hours=STALE_BACKUP_HOURS)
    stale = BackupRecord.objects.filter(
        status=BackupRecord.Status.RUNNING,
        started_at__lt=cutoff,
    )
    count = stale.update(
        status=BackupRecord.Status.FAILED,
        finished_at=now,
        error_message="Backup process appears to have stopped before completion.",
    )
    return count

def prune_old_backups():
    successful = list(BackupRecord.objects.filter(status=BackupRecord.Status.SUCCESS).order_by("-finished_at", "-id"))
    for record in successful[RETENTION_COUNT:]:
        (backup_root() / record.filename).unlink(missing_ok=True)
        _delete_remote(record)
        record.delete()

def create_backup(*, trigger=BackupRecord.Trigger.SCHEDULED, initiated_by=None, initiated_by_id=None):
    now = timezone.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    record_kwargs = {
        "filename": f"babaei-backup-{stamp}.tar.gz",
        "status": BackupRecord.Status.RUNNING,
        "trigger": trigger,
        "started_at": now,
    }
    if initiated_by is not None:
        record_kwargs["initiated_by"] = initiated_by
    elif initiated_by_id is not None:
        record_kwargs["initiated_by_id"] = initiated_by_id
    record = BackupRecord.objects.create(**record_kwargs)
    work_dir = Path(tempfile.mkdtemp(prefix="babaei-backup-"))
    archive_plain = work_dir / f"babaei-backup-{stamp}.tar.gz"
    final_path = None
    try:
        root = Path(os.environ.get("BACKUP_PROJECT_ROOT", settings.BASE_DIR.parent))
        payload = work_dir / "payload"
        payload.mkdir()
        project_dir = payload / "project"
        project_dir.mkdir()
        _copy_tree(root, project_dir)
        # Runtime data is exported separately so it is not duplicated inside
        # the project tree. Environment files are NEVER archived: secrets must
        # be restored/configured separately on the target server.
        for runtime_path in (
            project_dir / "data" / "database",
            project_dir / "data" / "media",
            project_dir / "data" / "backups",
            project_dir / "data" / "logs",
            project_dir / "config" / "data" / "static",
        ):
            shutil.rmtree(runtime_path, ignore_errors=True)
        (project_dir / ".env").unlink(missing_ok=True)
        (project_dir / "config" / ".env").unlink(missing_ok=True)

        db_dir = payload / "database"
        db_dir.mkdir()
        db_type = _dump_database(db_dir / "database.dump")

        media_dir = Path(settings.MEDIA_ROOT)
        if media_dir.exists():
            _copy_tree(media_dir, payload / "media")

        metadata = {
            "backup_version": BACKUP_VERSION,
            "project": "Babaei",
            "created_at": timezone.now().isoformat(),
            "database": db_type,
            "database_included": True,
            "media_included": True,
            "project_included": True,
            "retention_count": RETENTION_COUNT,
            "encrypted": bool(os.environ.get("BACKUP_ENCRYPTION_KEY")),
            "record_id": record.pk,
        }
        import json
        (payload / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        with tarfile.open(archive_plain, "w:gz") as archive:
            archive.add(payload, arcname="backup")

        # Validate the archive before it becomes a successful backup record.
        with tarfile.open(archive_plain, "r:gz") as archive:
            names = set(archive.getnames())
            required = {"backup/metadata.json", "backup/database/database.dump"}
            missing = required - names
            if missing:
                raise RuntimeError(f"Backup archive is incomplete: missing {sorted(missing)}")

        final_name = archive_plain.name + (".enc" if os.environ.get("BACKUP_ENCRYPTION_KEY") else "")
        final_path = backup_root() / final_name
        staging_path = backup_root() / f".{final_name}.{uuid4().hex}.tmp"
        encrypted = _encrypt(archive_plain, staging_path)
        os.replace(staging_path, final_path)
        checksum = _sha256(final_path)
        remote_key, backend = _upload_remote(final_path, f"{os.environ.get('BACKUP_S3_PREFIX', 'babaei')}/{final_name}")

        record.filename = final_name
        record.status = BackupRecord.Status.SUCCESS
        record.finished_at = timezone.now()
        record.size_bytes = final_path.stat().st_size
        record.sha256 = checksum
        record.storage_backend = backend
        record.remote_key = remote_key
        record.encrypted = encrypted
        record.includes_database = True
        record.includes_media = True
        record.includes_project = True
        record.save()
        prune_old_backups()
        return record
    except Exception as exc:
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        if "staging_path" in locals():
            staging_path.unlink(missing_ok=True)
        record.status = BackupRecord.Status.FAILED
        record.finished_at = timezone.now()
        record.error_message = str(exc)[:10000]
        record.save(update_fields=("status", "finished_at", "error_message"))
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

def _same_period(last_success, now, config):
    local_now = timezone.localtime(now)
    if config.frequency == BackupSettings.Frequency.DAILY:
        period_start = local_now.date()
    elif config.frequency == BackupSettings.Frequency.WEEKLY:
        days_since_target = (local_now.weekday() - config.weekday) % 7
        period_start = local_now.date() - timedelta(days=days_since_target)
    elif config.frequency == BackupSettings.Frequency.MONTHLY:
        period_start = local_now.date().replace(day=1)
    else:
        return False

    if not last_success:
        return True

    last_date = timezone.localtime(last_success.finished_at or last_success.created_at).date()
    return last_date < period_start


def is_scheduled_run_due(now=None):
    now = now or timezone.now()
    recover_stale_backups(now)
    config = BackupSettings.get_solo()
    if not config.enabled:
        return False

    local_now = timezone.localtime(now)
    target = config.run_time
    current_minutes = local_now.hour * 60 + local_now.minute
    target_minutes = target.hour * 60 + target.minute

    if config.frequency == BackupSettings.Frequency.DAILY:
        if current_minutes < target_minutes:
            return False
    elif config.frequency == BackupSettings.Frequency.WEEKLY:
        if local_now.weekday() == config.weekday and current_minutes < target_minutes:
            return False
    elif config.frequency == BackupSettings.Frequency.MONTHLY:
        if local_now.day < config.day_of_month:
            return False
        if local_now.day == config.day_of_month and current_minutes < target_minutes:
            return False

    last_success = BackupRecord.objects.filter(
        status=BackupRecord.Status.SUCCESS,
        trigger=BackupRecord.Trigger.SCHEDULED,
    ).order_by("-finished_at", "-id").first()
    return _same_period(last_success, now, config)
