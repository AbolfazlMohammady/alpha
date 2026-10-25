from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
import os
import urllib.error
import urllib.request

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import SettlementBatch
from .services import validate_settlement_batch_eligibility


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
    multiplier_value = os.environ.get("PAYOUT_AMOUNT_MULTIPLIER", "").strip()
    payout_currency = os.environ.get("PAYOUT_API_CURRENCY", "").strip().upper()
    if not multiplier_value or not payout_currency:
        raise PayoutNotConfigured(
            "قبل از واریز باید واحد مبالغ فروشگاه و واحد موردنیاز بانک بررسی و "
            "PAYOUT_AMOUNT_MULTIPLIER و PAYOUT_API_CURRENCY صریحاً تنظیم شوند."
        )
    try:
        multiplier = int(multiplier_value)
    except ValueError as exc:
        raise PayoutNotConfigured("PAYOUT_AMOUNT_MULTIPLIER باید عدد صحیح باشد.") from exc
    if multiplier <= 0:
        raise PayoutNotConfigured("PAYOUT_AMOUNT_MULTIPLIER باید مثبت باشد.")
    response_paths = {
        "reference": os.environ.get("PAYOUT_RESPONSE_REFERENCE_PATH", "").strip(),
        "status": os.environ.get("PAYOUT_RESPONSE_STATUS_PATH", "").strip(),
        "amount": os.environ.get("PAYOUT_RESPONSE_AMOUNT_PATH", "").strip(),
        "currency": os.environ.get("PAYOUT_RESPONSE_CURRENCY_PATH", "").strip(),
    }
    missing_paths = [name for name, path_value in response_paths.items() if not path_value]
    if missing_paths:
        raise PayoutNotConfigured(
            "نگاشت پاسخ بانک باید صریح تنظیم شود؛ مسیرهای مرجع، وضعیت نهایی، مبلغ واقعی و ارز الزامی‌اند."
        )

    with transaction.atomic():
        batch = SettlementBatch.objects.select_for_update().select_related("vendor").get(pk=batch_id)
        if batch.status != SettlementBatch.Status.APPROVED:
            raise ValidationError("فقط تسویه تأییدشده را می‌توان برای واریز ارسال کرد.")
        validate_settlement_batch_eligibility(batch)
        if not batch.vendor.bank_details_verified_at or not batch.vendor.bank_iban or not batch.vendor.bank_account_name:
            raise ValidationError("اطلاعات بانکی تأییدشده فروشنده کامل نیست.")
        if batch.payable_amount <= 0:
            raise ValidationError("مبلغ واریز باید مثبت باشد.")
        from .models import LedgerAccount
        from .services import account_balance, get_system_account
        bank_account = get_system_account(
            "platform_bank",
            "حساب بانکی پلتفرم",
            LedgerAccount.Kind.ASSET,
            currency=batch.currency,
        )
        bank_account = LedgerAccount.objects.select_for_update().get(pk=bank_account.pk)
        vendor_payable = get_system_account(
            f"vendor_payable_{batch.vendor_id}",
            f"بستانکاری فروشنده: {batch.vendor.store_name}",
            LedgerAccount.Kind.LIABILITY,
            currency=batch.currency,
            vendor=batch.vendor,
        )
        carrier_payable = get_system_account(
            "carrier_payable", "بدهی به شرکت‌های حمل", LedgerAccount.Kind.LIABILITY, currency=batch.currency
        )
        shipping_funds = get_system_account(
            "shipping_funds_payable", "وجوه تخصیص‌یافته به حمل", LedgerAccount.Kind.LIABILITY, currency=batch.currency
        )
        unidentified_receipt = get_system_account(
            "gateway_unidentified_receipt", "واریزی مازاد درگاه در انتظار بررسی",
            LedgerAccount.Kind.LIABILITY, currency=batch.currency
        )
        vendor_payable = LedgerAccount.objects.select_for_update().get(pk=vendor_payable.pk)
        vendor_payable_balance = account_balance(vendor_payable)
        if vendor_payable_balance < batch.payable_amount:
            raise PayoutError(
                "مانده دفترکل همین فروشنده از مبلغ این تسویه کمتر است؛ پیش از واریز، مغایرت حسابداری را بررسی کن."
            )
        # Protect every other vendor's payable balance and all restricted funds
        # before deciding how much of the platform bank balance is freely usable.
        other_vendor_payables = 0
        other_accounts = LedgerAccount.objects.filter(
            kind=LedgerAccount.Kind.LIABILITY,
            currency=batch.currency,
            code__startswith="vendor_payable_",
        ).exclude(pk=vendor_payable.pk)
        for account in other_accounts:
            other_vendor_payables += max(account_balance(account), 0)
        restricted_liabilities = (
            max(vendor_payable_balance - batch.payable_amount, 0)
            + other_vendor_payables
            + max(account_balance(carrier_payable), 0)
            + max(account_balance(shipping_funds), 0)
            + max(account_balance(unidentified_receipt), 0)
        )
        available_amount = account_balance(bank_account) - restricted_liabilities
        if available_amount < batch.payable_amount:
            raise PayoutError(
                f"موجودی آزاد حساب بانکی برای این واریز کافی نیست؛ "
                f"موجودی آزاد پس از تعهدات دیگر: {available_amount}، مبلغ تسویه: {batch.payable_amount}. "
                "ابتدا تسویه‌های ورودی و تعهدات حمل را تطبیق کن."
            )
        # Lock the batch before making the external call. If the response is
        # ambiguous, the batch stays PROCESSING and must be reconciled rather
        # than blindly retried (which could duplicate a bank transfer).
        batch.status = SettlementBatch.Status.PROCESSING
        batch.failure_reason = ""
        batch.payout_attempts += 1
        payout_idempotency_key = f"{batch.idempotency_key}:attempt:{batch.payout_attempts}"
        batch.save(update_fields=("status", "failure_reason", "payout_attempts", "updated_at"))
        payload = {
            "idempotency_key": payout_idempotency_key,
            "client_reference": str(batch.uuid),
            "amount": batch.payable_amount * multiplier,
            "currency": payout_currency,
            "beneficiary": {
                "iban": batch.vendor.bank_iban.replace(" ", "").upper(),
                "account_name": batch.vendor.bank_account_name,
            },
            "description": f"تسویه فروشنده {batch.vendor.store_name}",
        }

    url = base_url + "/" + path.lstrip("/")
    auth_header = os.environ.get("PAYOUT_API_AUTH_HEADER", "Authorization")
    auth_scheme = os.environ.get("PAYOUT_API_AUTH_SCHEME", "Bearer").strip()
    auth_value = f"{auth_scheme} {token}" if auth_scheme else token
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            auth_header: auth_value,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": payout_idempotency_key,
            "User-Agent": "BabaeiMarketplace/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(1_000_000).decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise PayoutError("ساختار پاسخ سرویس واریز معتبر نیست.")
    except urllib.error.HTTPError as exc:
        # This adapter has no provider-specific contract proving that an HTTP
        # error means no transfer occurred. Even 4xx responses can represent a
        # duplicate/idempotency conflict, so never mark the payout retryable
        # from HTTP status alone.
        with transaction.atomic():
            locked = SettlementBatch.objects.select_for_update().get(pk=batch_id)
            locked.status = SettlementBatch.Status.PROCESSING
            locked.failure_reason = (
                f"پاسخ HTTP {exc.code}؛ عدم انجام انتقال اثبات نشده است. "
                "وضعیت باید با سرویس مالی/گردش حساب تطبیق داده شود."
            )[:4000]
            locked.save(update_fields=("status", "failure_reason"))
        raise PayoutError(f"سرویس واریز با HTTP {exc.code} پاسخ داد؛ تسویه برای جلوگیری از پرداخت تکراری قفل ماند.") from exc
    except PayoutError as exc:
        SettlementBatch.objects.filter(
            pk=batch_id, status=SettlementBatch.Status.PROCESSING
        ).update(failure_reason=str(exc)[:4000])
        raise
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
            failure_reason="پاسخ قطعی از سرویس واریز دریافت نشد؛ پیش از هر تلاش مجدد، وضعیت را با بانک/سرویس مالی تطبیق دهید."
        )
        raise PayoutError("نتیجه درخواست واریز نامشخص است؛ برای جلوگیری از واریز تکراری، ابتدا مغایرت‌گیری کنید.") from exc

    def path_value(path):
        value = data
        for part in path.split(".") if path else []:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    reference = str(path_value(response_paths["reference"]) or "").strip()[:180]
    provider_status = str(path_value(response_paths["status"]) or "").strip().lower()
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
        if not reference:
            SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
                failure_reason="سرویس موفقیت را اعلام کرده اما شناسه مرجع ندارد؛ تطبیق با گردش حساب لازم است."
            )
            raise PayoutError("شناسه مرجع واریز در پاسخ موجود نیست؛ تسویه قفل شد تا تطبیق دستی.")
        raw_actual_amount = path_value(response_paths["amount"])
        raw_response_currency = path_value(response_paths["currency"])
        if str(raw_response_currency or "").strip().upper() != payout_currency:
            SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
                failure_reason="ارز اعلام‌شده توسط سرویس واریز با ارز پیکربندی‌شده برابر نیست؛ تطبیق بانکی لازم است."
            )
            raise PayoutError("ارز پاسخ سرویس واریز با تنظیمات مطابقت ندارد؛ تسویه برای بررسی باقی ماند.")
        actual_amount = None
        if raw_actual_amount is not None:
            try:
                normalized_amount = Decimal(str(raw_actual_amount)) / Decimal(multiplier)
                if normalized_amount != normalized_amount.to_integral_value():
                    raise InvalidOperation
                actual_amount = int(normalized_amount)
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
                    failure_reason="سرویس واریز موفقیت را اعلام کرده اما مبلغ پاسخ قابل تبدیل نیست؛ تطبیق بانکی لازم است."
                )
                raise PayoutError("مبلغ پاسخ سرویس واریز معتبر نیست؛ تسویه برای بررسی باقی ماند.")
        try:
            batch = record_payout_result(
                batch_id=batch_id,
                provider_reference=reference,
                succeeded=True,
                actual_amount=actual_amount,
            )
        except ValidationError as exc:
            SettlementBatch.objects.filter(pk=batch_id, status=SettlementBatch.Status.PROCESSING).update(
                failure_reason=f"نتیجه واریز نیازمند تطبیق دستی است: {exc}"[:4000]
            )
            raise PayoutError("نتیجه واریز با سابقه مالی تطبیق ندارد؛ تسویه برای بررسی قفل شد.") from exc
    elif provider_status in {"failed", "failure", "rejected", "cancelled", "canceled", "declined"}:
        from .services import record_payout_result
        batch = record_payout_result(
            batch_id=batch_id,
            provider_reference=reference,
            succeeded=False,
            failure_reason=f"سرویس واریز وضعیت نهایی ناموفق را گزارش کرد: {provider_status}",
        )
    else:
        batch = SettlementBatch.objects.get(pk=batch_id)
        batch.failure_reason = (
            f"وضعیت سرویس واریز هنوز نهایی نیست ({provider_status or 'نامشخص'}). "
            "تسویه قفل می‌ماند تا وضعیت نهایی با بانک تطبیق داده شود."
        )
        batch.save(update_fields=("failure_reason",))
    return batch
