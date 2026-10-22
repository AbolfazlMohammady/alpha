from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import SettlementBatch


class PayoutError(Exception):
    pass


class PayoutNotConfigured(PayoutError):
    pass


def submit_settlement_payout(batch_id: int):
    """Submit one approved batch to a contract-specific payout gateway.

    This adapter is intentionally disabled until a real bank/PSP API contract,
    endpoint and credentials are configured. It never marks a transfer paid
    merely because an API accepted the request.
    """
    base_url = os.environ.get("PAYOUT_API_BASE_URL", "").rstrip("/")
    token = os.environ.get("PAYOUT_API_TOKEN", "")
    path = os.environ.get("PAYOUT_API_PATH", "")
    try:
        timeout = max(3, min(30, int(os.environ.get("PAYOUT_API_TIMEOUT_SECONDS", "10"))))
    except ValueError:
        timeout = 10
    if not base_url or not token or not path:
        raise PayoutNotConfigured(
            "سرویس واریز خودکار پیکربندی نشده است؛ قرارداد API بانکی/پرداختی و اعتبارنامه معتبر لازم است."
        )
    if not base_url.startswith("https://"):
        raise PayoutNotConfigured("سرویس واریز در محیط عملیاتی باید از HTTPS استفاده کند.")

    with transaction.atomic():
        batch = SettlementBatch.objects.select_for_update().select_related("vendor").get(pk=batch_id)
        if batch.status != SettlementBatch.Status.APPROVED:
            raise ValidationError("فقط تسویه تأییدشده را می‌توان برای واریز ارسال کرد.")
        if not batch.vendor.bank_details_verified_at or not batch.vendor.bank_iban or not batch.vendor.bank_account_name:
            raise ValidationError("اطلاعات بانکی تأییدشده فروشنده کامل نیست.")
        if batch.payable_amount <= 0:
            raise ValidationError("مبلغ واریز باید مثبت باشد.")
        # Lock the batch before making the external call. If the response is
        # ambiguous, the batch stays PROCESSING and must be reconciled rather
        # than blindly retried (which could duplicate a bank transfer).
        batch.status = SettlementBatch.Status.PROCESSING
        batch.failure_reason = ""
        batch.save(update_fields=("status", "failure_reason"))
        payload = {
            "idempotency_key": batch.idempotency_key,
            "client_reference": str(batch.uuid),
            "amount": batch.payable_amount,
            "currency": batch.currency,
            "beneficiary": {
                "iban": batch.vendor.bank_iban.replace(" ", "").upper(),
                "account_name": batch.vendor.bank_account_name,
            },
            "description": f"تسویه فروشنده {batch.vendor.store_name}",
        }

    url = base_url + "/" + path.lstrip("/")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": batch.idempotency_key,
            "User-Agent": "BabaeiMarketplace/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(1_000_000).decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise PayoutError("ساختار پاسخ سرویس واریز معتبر نیست.")
    except urllib.error.HTTPError as exc:
        # A 5xx can be ambiguous: provider may have processed the request.
        with transaction.atomic():
            locked = SettlementBatch.objects.select_for_update().get(pk=batch_id)
            locked.failure_reason = (
                f"پاسخ HTTP {exc.code}؛ وضعیت واریز باید با سرویس مالی تطبیق داده شود."
            )[:4000]
            if 400 <= exc.code < 500 and exc.code not in (408, 429):
                locked.status = SettlementBatch.Status.FAILED
            locked.save(update_fields=("status", "failure_reason"))
        raise PayoutError(f"سرویس واریز با HTTP {exc.code} پاسخ داد؛ وضعیت تراکنش را تطبیق دهید.") from exc
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
            failure_reason="پاسخ قطعی از سرویس واریز دریافت نشد؛ پیش از هر تلاش مجدد، وضعیت را با بانک/سرویس مالی تطبیق دهید."
        )
        raise PayoutError("نتیجه درخواست واریز نامشخص است؛ برای جلوگیری از واریز تکراری، ابتدا مغایرت‌گیری کنید.") from exc

    reference = str(data.get("transfer_id") or data.get("reference") or data.get("id") or "")[:180]
    provider_status = str(data.get("status") or "").lower()
    if not reference:
        SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
            failure_reason="سرویس درخواست را پاسخ داد اما شناسه انتقال نداشت؛ تطبیق دستی لازم است."
        )
        raise PayoutError("سرویس واریز شناسه انتقال برنگرداند؛ تسویه برای بررسی باقی ماند.")
    batch = SettlementBatch.objects.get(pk=batch_id)
    batch.payout_reference = reference
    batch.failure_reason = ""
    batch.save(update_fields=("payout_reference", "failure_reason"))
    if provider_status in {"paid", "completed", "success", "succeeded"}:
        from .services import record_payout_result
        batch = record_payout_result(batch_id=batch_id, provider_reference=reference, succeeded=True)
    return batch
