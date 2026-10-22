from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


class CarrierError(Exception):
    """Safe-to-display carrier integration error."""


class CarrierNotConfigured(CarrierError):
    pass


@dataclass(frozen=True)
class ShippingQuote:
    provider: str
    amount: int
    currency: str = "IRT"
    reference: str = ""
    expires_at: str | None = None
    raw: dict | None = None


class JsonCarrierClient:
    """Configurable JSON REST adapter.

    Carrier-specific URL paths and response schemas must be verified against the
    account's current commercial API documentation. No provider endpoint or
    credentials are assumed or hard-coded.
    """

    provider_code = "manual"

    def __init__(self, *, base_url=None, token=None, quote_path=None, shipment_path=None, tracking_path=None, timeout=None):
        prefix = self.provider_code.upper()
        self.base_url = (base_url if base_url is not None else os.environ.get(f"{prefix}_API_BASE_URL", "")).rstrip("/")
        self.token = token if token is not None else os.environ.get(f"{prefix}_API_TOKEN", "")
        self.quote_path = quote_path if quote_path is not None else os.environ.get(f"{prefix}_QUOTE_PATH", "")
        self.shipment_path = shipment_path if shipment_path is not None else os.environ.get(f"{prefix}_SHIPMENT_PATH", "")
        self.tracking_path = tracking_path if tracking_path is not None else os.environ.get(f"{prefix}_TRACKING_PATH", "")
        self.timeout = int(timeout if timeout is not None else os.environ.get("CARRIER_API_TIMEOUT_SECONDS", "10"))

    def _require(self, path):
        if not self.base_url or not path or not self.token:
            raise CarrierNotConfigured(
                f"اتصال {self.provider_code} پیکربندی نشده است؛ آدرس API، مسیر endpoint و توکن معتبر لازم است."
            )
        if not self.base_url.startswith("https://"):
            raise CarrierNotConfigured("در محیط عملیاتی، آدرس API شرکت حمل‌ونقل باید HTTPS باشد.")

    def _request(self, path, *, method="POST", payload=None):
        self._require(path)
        url = self.base_url + "/" + path.lstrip("/")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        auth_header = os.environ.get(f"{self.provider_code.upper()}_API_AUTH_HEADER", "Authorization")
        auth_scheme = os.environ.get(f"{self.provider_code.upper()}_API_AUTH_SCHEME", "Bearer").strip()
        auth_value = f"{auth_scheme} {self.token}" if auth_scheme else self.token
        headers = {
            auth_header: auth_value,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "BabaeiMarketplace/1.0",
        }
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_000)
                if response.status < 200 or response.status >= 300:
                    raise CarrierError(f"شرکت حمل‌ونقل پاسخ ناموفق HTTP {response.status} برگرداند.")
                parsed = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(parsed, dict):
                    raise CarrierError("ساختار پاسخ شرکت حمل‌ونقل معتبر نیست.")
                return parsed
        except urllib.error.HTTPError as exc:
            # Never return raw response bodies; they may contain personal data.
            if exc.code in (401, 403):
                raise CarrierError("دسترسی API شرکت حمل‌ونقل رد شد؛ اعتبارنامه و قرارداد را بررسی کنید.") from exc
            if exc.code == 429:
                raise CarrierError("محدودیت تعداد درخواست API شرکت حمل‌ونقل اعمال شده است.") from exc
            raise CarrierError(f"API شرکت حمل‌ونقل با HTTP {exc.code} پاسخ داد.") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CarrierError("ارتباط با شرکت حمل‌ونقل برقرار نشد؛ دوباره تلاش کنید.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CarrierError("پاسخ API شرکت حمل‌ونقل JSON معتبر نیست.") from exc

    @staticmethod
    def _path_value(data, path):
        if not path:
            return None
        value = data
        for part in path.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                return None
        return value

    def _amount(self, data):
        prefix = self.provider_code.upper()
        configured_path = os.environ.get(f"{prefix}_QUOTE_AMOUNT_PATH", "")
        value = self._path_value(data, configured_path) if configured_path else None
        if value is None:
            # Common top-level fields are a fallback only; official response
            # mapping should be configured for the contracted carrier API.
            for key in ("amount", "price", "cost", "shipping_cost", "total"):
                value = data.get(key)
                if value is not None:
                    break
        if value is None:
            raise CarrierError("کلید مبلغ در پاسخ API پیدا نشد؛ مسیر مبلغ را مطابق مستندات رسمی تنظیم کنید.")
        prefix = self.provider_code.upper()
        try:
            raw_amount = Decimal(str(value))
            divisor = Decimal(os.environ.get(f"{prefix}_AMOUNT_DIVISOR", "1"))
            raw_currency = str(data.get("currency", "")).strip().upper()
            if divisor <= 0:
                raise InvalidOperation
            if raw_currency in {"IRR", "RIAL", "RIALS", "ریال"} and divisor == 1:
                raise CarrierError("API مبلغ را به ریال اعلام کرده؛ ضریب تبدیل به واحد پروژه را تنظیم کنید.")
            normalized = raw_amount / divisor
            if normalized != normalized.to_integral_value():
                raise CarrierError("مبلغ حمل پس از تبدیل واحد، عدد صحیح قابل ثبت در حسابداری نیست.")
            amount = int(normalized)
        except CarrierError:
            raise
        except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
            raise CarrierError("مبلغ اعلام‌شده توسط شرکت حمل‌ونقل قابل‌خواندن نیست.") from exc
        if amount < 0:
            raise CarrierError("شرکت حمل‌ونقل هزینه منفی اعلام کرده است.")
        return amount

    def quote(self, payload: dict) -> ShippingQuote:
        data = self._request(self.quote_path, payload=payload)
        prefix = self.provider_code.upper()
        reference_path = os.environ.get(f"{prefix}_QUOTE_REFERENCE_PATH", "")
        expiry_path = os.environ.get(f"{prefix}_QUOTE_EXPIRES_PATH", "")
        reference = self._path_value(data, reference_path) if reference_path else None
        expiry = self._path_value(data, expiry_path) if expiry_path else None
        return ShippingQuote(
            provider=self.provider_code,
            amount=self._amount(data),
            currency="IRT",
            reference=str(reference or data.get("quote_id") or data.get("reference") or data.get("id") or "")[:160],
            expires_at=expiry or data.get("expires_at"),
            raw=data,
        )

    def create_shipment(self, payload: dict) -> dict:
        data = self._request(self.shipment_path, payload=payload)
        prefix = self.provider_code.upper()
        tracking_path = os.environ.get(f"{prefix}_SHIPMENT_TRACKING_PATH", "")
        shipment_path = os.environ.get(f"{prefix}_SHIPMENT_ID_PATH", "")
        label_path = os.environ.get(f"{prefix}_SHIPMENT_LABEL_PATH", "")
        tracking = self._path_value(data, tracking_path) if tracking_path else None
        shipment_id = self._path_value(data, shipment_path) if shipment_path else None
        label = self._path_value(data, label_path) if label_path else None
        tracking = tracking or data.get("tracking_number") or data.get("tracking_code") or data.get("barcode") or ""
        shipment_id = shipment_id or data.get("shipment_id") or data.get("id") or data.get("reference") or ""
        label = label or data.get("label_url") or data.get("label") or ""
        if not tracking and not shipment_id:
            raise CarrierError("مرسوله در پاسخ API شناسه یا کد رهگیری ندارد؛ وضعیت را از پنل شرکت بررسی کنید.")
        return {
            "external_shipment_id": str(shipment_id)[:160],
            "tracking_number": str(tracking)[:160],
            "label_url": str(label)[:1000],
            "raw": data,
        }

    def track(self, tracking_number: str) -> dict:
        if not tracking_number:
            raise ValidationError("کد رهگیری الزامی است.")
        prefix = self.provider_code.upper()
        path = self.tracking_path.format(tracking_number=urllib.parse.quote(tracking_number, safe=""))
        data = self._request(path, method="GET")
        status_path = os.environ.get(f"{prefix}_TRACKING_STATUS_PATH", "")
        cost_path = os.environ.get(f"{prefix}_TRACKING_COST_PATH", "")
        status = self._path_value(data, status_path) if status_path else None
        cost = self._path_value(data, cost_path) if cost_path else None
        if status is not None:
            data = {**data, "status": status}
        if cost is not None:
            try:
                divisor = Decimal(os.environ.get(f"{prefix}_AMOUNT_DIVISOR", "1"))
                raw_currency = str(data.get("currency", "")).strip().upper()
                if raw_currency in {"IRR", "RIAL", "RIALS", "ریال"} and divisor == 1:
                    raise CarrierError("API مبلغ را به ریال اعلام کرده؛ ضریب تبدیل به واحد پروژه را تنظیم کنید.")
                normalized_cost = Decimal(str(cost)) / divisor
                if normalized_cost != normalized_cost.to_integral_value():
                    raise CarrierError("هزینه رهگیری پس از تبدیل واحد عدد صحیح نیست.")
                cost = int(normalized_cost)
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise CarrierError("هزینه نهایی حمل قابل تبدیل به واحد پروژه نیست.") from exc
            data = {**data, "actual_cost": cost}
        return data


class TipaxClient(JsonCarrierClient):
    provider_code = "TIPAX"


class NationalPostClient(JsonCarrierClient):
    provider_code = "POST"


PROVIDERS = {
    "tipax": TipaxClient,
    "post": NationalPostClient,
}


def get_carrier(provider: str) -> JsonCarrierClient:
    client_class = PROVIDERS.get(provider)
    if not client_class:
        raise ValidationError("شرکت حمل‌ونقل انتخاب‌شده پشتیبانی نمی‌شود.")
    return client_class()


def validate_quote_input(payload: dict):
    try:
        weight = int(payload.get("weight_grams", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError("وزن بسته باید عدد صحیح و بر حسب گرم باشد.") from exc
    if weight <= 0 or weight > 100_000_000:
        raise ValidationError("وزن بسته باید بیشتر از صفر باشد.")
    for key in ("origin_postal_code", "destination_postal_code"):
        value = str(payload.get(key, "")).strip()
        if len(value) < 5 or len(value) > 20:
            raise ValidationError(f"{key}: کد پستی معتبر وارد کنید.")
    return {
        "weight_grams": weight,
        "origin_postal_code": str(payload["origin_postal_code"]).strip(),
        "destination_postal_code": str(payload["destination_postal_code"]).strip(),
        "length_cm": _optional_dimension(payload.get("length_cm"), "طول"),
        "width_cm": _optional_dimension(payload.get("width_cm"), "عرض"),
        "height_cm": _optional_dimension(payload.get("height_cm"), "ارتفاع"),
        "declared_value": _optional_nonnegative(payload.get("declared_value"), "ارزش اظهارشده"),
        "service_level": str(payload.get("service_level", "standard"))[:40],
    }


def _optional_dimension(value, label):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} بسته باید عدد صحیح باشد.") from exc
    if number <= 0 or number > 100_000:
        raise ValidationError(f"{label} بسته خارج از محدوده مجاز است.")
    return number


def _optional_nonnegative(value, label):
    if value in (None, ""):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} باید عدد صحیح باشد.") from exc
    if number < 0:
        raise ValidationError(f"{label} نمی‌تواند منفی باشد.")
    return number
