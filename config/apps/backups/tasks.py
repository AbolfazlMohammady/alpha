from celery import shared_task

from .services import backup_lock, create_backup
from .models import BackupRecord


@shared_task(name="backups.create_backup")
def create_backup_task(trigger="scheduled", initiated_by_id=None):
    with backup_lock() as acquired:
        if not acquired:
            return None
        record = create_backup(
            trigger=trigger,
            initiated_by_id=initiated_by_id,
        )
        return record.pk


@shared_task(name="backups.run_scheduled_backup_check")
def run_scheduled_backup_check():
    from .services import is_scheduled_run_due

    if not is_scheduled_run_due():
        return None
    with backup_lock() as acquired:
        if not acquired:
            return None
        record = create_backup(trigger=BackupRecord.Trigger.SCHEDULED)
        return record.pk
