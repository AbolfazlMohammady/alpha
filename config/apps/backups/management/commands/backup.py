from django.core.management.base import BaseCommand, CommandError
from apps.backups.models import BackupRecord
from apps.backups.services import backup_lock, create_backup, is_scheduled_run_due

class Command(BaseCommand):
    help = "Create or schedule Babaei disaster-recovery backups."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("run", "run-scheduled"), nargs="?", default="run-scheduled")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "run-scheduled" and not is_scheduled_run_due():
            self.stdout.write("Backup is not due.")
            return
        with backup_lock() as acquired:
            if not acquired:
                self.stdout.write("Another backup is already running.")
                return
            try:
                record = create_backup(
                    trigger=BackupRecord.Trigger.SCHEDULED
                    if action == "run-scheduled"
                    else BackupRecord.Trigger.MANUAL
                )
            except Exception as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Backup completed: {record.filename} ({record.size_bytes} bytes)"))
