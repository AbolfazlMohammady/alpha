from datetime import time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from .models import BackupRecord, BackupSettings
from .services import RETENTION_COUNT, _dump_database, is_scheduled_run_due, prune_old_backups, recover_stale_backups


class BackupScheduleTests(TestCase):
    def setUp(self):
        self.config = BackupSettings.get_solo()

    @freeze_time("2026-10-10 03:00:00")
    def test_weekly_schedule_is_due_once_per_week(self):
        self.config.frequency = BackupSettings.Frequency.WEEKLY
        self.config.weekday = 5
        self.config.run_time = time(3, 0)
        self.config.save()

        self.assertTrue(is_scheduled_run_due())

        BackupRecord.objects.create(
            filename="week-1.tar.gz",
            status=BackupRecord.Status.SUCCESS,
            trigger=BackupRecord.Trigger.SCHEDULED,
            finished_at=timezone.now(),
        )
        self.assertFalse(is_scheduled_run_due())

        with freeze_time("2026-10-17 03:00:00"):
            self.assertTrue(is_scheduled_run_due())


class BackupRetentionTests(TestCase):
    @patch("apps.backups.services.backup_root")
    def test_only_five_successful_backups_are_retained(self, backup_root_mock):
        root = Path(self._temp_backup_dir())
        backup_root_mock.return_value = root
        for index in range(6):
            filename = f"backup-{index}.tar.gz"
            (root / filename).write_text("backup", encoding="utf-8")
            BackupRecord.objects.create(
                filename=filename,
                status=BackupRecord.Status.SUCCESS,
                trigger=BackupRecord.Trigger.SCHEDULED,
                finished_at=timezone.now() + timedelta(seconds=index),
            )

        prune_old_backups()

        self.assertEqual(
            BackupRecord.objects.filter(status=BackupRecord.Status.SUCCESS).count(),
            RETENTION_COUNT,
        )
        self.assertFalse((root / "backup-0.tar.gz").exists())

    def _temp_backup_dir(self):
        import tempfile
        return tempfile.mkdtemp(prefix="babaei-test-backups-")


class BackupRecoveryTests(TestCase):
    @freeze_time("2026-10-11 12:00:00")
    def test_stale_running_backup_is_marked_failed(self):
        BackupRecord.objects.create(
            filename="stuck.tar.gz",
            status=BackupRecord.Status.RUNNING,
            trigger=BackupRecord.Trigger.SCHEDULED,
            started_at=timezone.now() - timedelta(hours=25),
        )
        self.assertEqual(recover_stale_backups(), 1)
        record = BackupRecord.objects.get(filename="stuck.tar.gz")
        self.assertEqual(record.status, BackupRecord.Status.FAILED)
        self.assertIn("stopped", record.error_message)

    @freeze_time("2026-10-11 12:00:00")
    def test_recent_running_backup_is_not_marked_failed(self):
        BackupRecord.objects.create(
            filename="active.tar.gz",
            status=BackupRecord.Status.RUNNING,
            trigger=BackupRecord.Trigger.SCHEDULED,
            started_at=timezone.now() - timedelta(hours=2),
        )
        self.assertEqual(recover_stale_backups(), 0)
        self.assertTrue(
            BackupRecord.objects.filter(
                filename="active.tar.gz",
                status=BackupRecord.Status.RUNNING,
            ).exists()
        )


class BackupDatabaseTests(TestCase):
    def test_sqlite_uses_consistent_online_backup(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-specific backup test")
        import tempfile
        destination = Path(tempfile.mktemp(suffix=".sqlite3"))
        try:
            backup_type = _dump_database(destination)
            self.assertEqual(backup_type, "sqlite-online-backup")
            self.assertTrue(destination.exists())
            self.assertGreater(destination.stat().st_size, 0)
        finally:
            destination.unlink(missing_ok=True)
