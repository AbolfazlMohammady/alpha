from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from apps.users.models import RoleUser


class Command(BaseCommand):
    help = "Create the application's bootstrap superuser from environment variables."

    def handle(self, *args, **options):
        import os

        phone = (os.environ.get("SUPERUSER_PHONE") or "").strip()
        password = os.environ.get("SUPERUSER_PASSWORD") or ""

        if not phone and not password:
            self.stdout.write("SUPERUSER_PHONE/PASSWORD are not configured; skipping superuser bootstrap.")
            return

        if not phone or not password:
            raise CommandError("Both SUPERUSER_PHONE and SUPERUSER_PASSWORD must be set together.")

        User = get_user_model()

        try:
            normalized_phone = User.objects.normalize_phone(phone)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        user = User.objects.filter(phone=normalized_phone).first()

        # There is exactly one technical Django-admin identity. Any other
        # account is stripped of staff/superuser flags on container startup.
        User.objects.exclude(phone=normalized_phone).filter(
            is_superuser=True,
        ).update(is_superuser=False, is_staff=False)

        if user is None:
            try:
                User.objects.create_superuser(
                    phone=normalized_phone,
                    password=password,
                    is_staff=True,
                    is_superuser=True,
                    is_active=True,
                    role=RoleUser.ADMIN,
                )
            except IntegrityError as exc:
                raise CommandError("Could not create the bootstrap superuser because of a database constraint.") from exc

            self.stdout.write(self.style.SUCCESS(f"Bootstrap superuser created: {normalized_phone}"))
            return

        changed = False
        if not user.is_superuser:
            user.is_superuser = True
            changed = True
        if not user.is_staff:
            user.is_staff = True
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if user.role != RoleUser.ADMIN:
            user.role = RoleUser.ADMIN
            changed = True

        if changed:
            user.save(update_fields=["is_superuser", "is_staff", "is_active", "role"])
            self.stdout.write(self.style.SUCCESS(f"Bootstrap superuser privileges restored: {normalized_phone}"))
        else:
            self.stdout.write("Bootstrap superuser already exists.")
