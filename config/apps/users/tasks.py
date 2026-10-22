from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import OTP


@shared_task
def cleanup_expired_otps():
    """Remove expired and legacy-used OTP challenges from the database."""
    cutoff = timezone.now()
    stale_used_cutoff = cutoff - timedelta(hours=1)
    deleted, _ = OTP.objects.filter(
        Q(expire_at__lte=cutoff)
        | Q(is_used=True, created_at__lte=stale_used_cutoff)
    ).delete()
    return {"deleted": deleted}
