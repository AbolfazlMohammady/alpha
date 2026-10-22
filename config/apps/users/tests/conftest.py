import pytest
from datetime import timedelta
from django.utils import timezone

from apps.users.models import OTP

@pytest.fixture
def otp(db):
    return OTP.objects.create(
        code= '123456',
        phone='+989339796368',
        expire_at= timezone.now() + timedelta(minutes=2)
    )