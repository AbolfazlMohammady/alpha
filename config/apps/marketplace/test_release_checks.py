"""Focused release smoke tests for marketplace, logistics, and accounting.

These tests use mocked carrier responses only. They never call a real carrier or bank API.
Run with: python manage.py test apps.marketplace.test_release_checks
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .carriers import CarrierNotConfigured, TipaxClient, validate_quote_input
from .models import JournalEntry, LedgerAccount, Vendor, VendorApplication
from apps.users.models import RoleUser
from .services import post_journal, trial_balance


class LogisticsReleaseChecks(TestCase):
    def valid_quote_payload(self):
        return {
            "weight_grams": 750,
            "origin_postal_code": "1234567890",
            "destination_postal_code": "0987654321",
            "length_cm": 25,
            "width_cm": 18,
            "height_cm": 12,
            "declared_value": 250000,
        }

    def test_quote_input_accepts_complete_iranian_parcel(self):
        result = validate_quote_input(self.valid_quote_payload())
        self.assertEqual(result["weight_grams"], 750)
        self.assertEqual(result["origin_postal_code"], "1234567890")
        self.assertEqual(result["declared_value"], 250000)

    def test_quote_input_rejects_non_ascii_or_wrong_length_postal_code(self):
        for postal_code in ("12345", "۱۲۳۴۵۶۷۸۹۰", "123456789A"):
            with self.subTest(postal_code=postal_code):
                payload = self.valid_quote_payload()
                payload["destination_postal_code"] = postal_code
                with self.assertRaises(ValidationError):
                    validate_quote_input(payload)

    def test_quote_input_requires_all_three_dimensions(self):
        payload = self.valid_quote_payload()
        del payload["height_cm"]
        with self.assertRaises(ValidationError):
            validate_quote_input(payload)

    def test_quote_input_rejects_fractional_weight(self):
        payload = self.valid_quote_payload()
        payload["weight_grams"] = 750.5
        with self.assertRaises(ValidationError):
            validate_quote_input(payload)

    def test_carrier_integration_fails_closed_without_api_configuration(self):
        client = TipaxClient(base_url="", token="", quote_path="/quote")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CarrierNotConfigured):
                client.quote(self.valid_quote_payload())


class AccountingReleaseChecks(TestCase):
    def setUp(self):
        self.cash = LedgerAccount.objects.create(
            code="release_test_cash",
            name="وجه نقد تست انتشار",
            kind=LedgerAccount.Kind.ASSET,
            currency="IRT",
        )
        self.revenue = LedgerAccount.objects.create(
            code="release_test_revenue",
            name="درآمد تست انتشار",
            kind=LedgerAccount.Kind.REVENUE,
            currency="IRT",
        )

    def lines(self, amount):
        return [
            {"account": self.cash, "debit": amount, "credit": 0},
            {"account": self.revenue, "debit": 0, "credit": amount},
        ]

    def test_balanced_journal_posts_once_for_same_idempotency_key(self):
        first, created_first = post_journal(
            idempotency_key="release-smoke-payment-001",
            kind="release_smoke",
            description="تست ثبت سند متوازن",
            lines=self.lines(125000),
        )
        second, created_second = post_journal(
            idempotency_key="release-smoke-payment-001",
            kind="release_smoke",
            description="تکرار تست ثبت سند",
            lines=self.lines(125000),
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.status, JournalEntry.Status.POSTED)
        self.assertEqual(first.lines.count(), 2)

    def test_unbalanced_journal_is_rejected_without_persisting(self):
        with self.assertRaises(ValidationError):
            post_journal(
                idempotency_key="release-smoke-unbalanced-001",
                kind="release_smoke",
                description="تست سند نامتوازن",
                lines=[
                    {"account": self.cash, "debit": 1000, "credit": 0},
                    {"account": self.revenue, "debit": 0, "credit": 999},
                ],
            )
        self.assertFalse(
            JournalEntry.objects.filter(
                idempotency_key="release-smoke-unbalanced-001"
            ).exists()
        )

    def test_idempotency_key_cannot_be_reused_for_different_amount(self):
        post_journal(
            idempotency_key="release-smoke-fingerprint-001",
            kind="release_smoke",
            description="مبلغ اصلی",
            lines=self.lines(1000),
        )
        with self.assertRaises(ValidationError):
            post_journal(
                idempotency_key="release-smoke-fingerprint-001",
                kind="release_smoke",
                description="مبلغ متفاوت",
                lines=self.lines(2000),
            )

    def test_trial_balance_remains_balanced_after_posting(self):
        post_journal(
            idempotency_key="release-smoke-trial-balance-001",
            kind="release_smoke",
            description="تست تراز آزمایشی",
            lines=self.lines(50000),
        )
        report = trial_balance()
        self.assertTrue(report["balanced"])



class VendorDashboardAccessTests(TestCase):
    def test_store_manager_without_vendor_row_gets_pending_vendor_profile(self):
        user = get_user_model().objects.create_user(
            phone="+989121234567",
            role=RoleUser.STORE_MANAGER,
            first_name="فروشگاه آزمایشی",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("marketplace:vendor_dashboard_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پنل فروشنده")
        vendor = Vendor.objects.get(user=user)
        self.assertEqual(vendor.status, Vendor.Status.PENDING)
        self.assertTrue(vendor.slug.startswith(f"store-{user.pk}-"))



class VendorApplicationWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            phone="+989121234568",
            password="test-password",
            email="seller@example.com",
            role=RoleUser.CUSTOMER,
        )
        self.client.force_login(self.user)

    def payload(self):
        return {
            "contact_name": "آزمایش فروشنده",
            "contact_email": "seller@example.com",
            "contact_phone": "+989121234568",
            "national_id": "1234567890",
            "store_name": "فروشگاه آزمایشی",
            "seller_type": "both",
            "province": "تهران",
            "city": "تهران",
            "postal_code": "1234567890",
            "address": "نشانی آزمایشی",
            "website_or_social": "https://example.com",
            "description": "عرضه محصولات در دسته پوشاک و اکسسوری با تأمین منظم",
        }

    def test_customer_can_submit_application_without_becoming_vendor(self):
        response = self.client.post(reverse("marketplace:vendor_application_page"), self.payload())
        self.assertEqual(response.status_code, 302)
        application = VendorApplication.objects.get(user=self.user)
        self.assertEqual(application.status, VendorApplication.Status.PENDING)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, RoleUser.CUSTOMER)
        self.assertFalse(Vendor.objects.filter(user=self.user).exists())

    def test_invalid_national_id_is_rejected(self):
        payload = self.payload()
        payload["national_id"] = "123"
        response = self.client.post(reverse("marketplace:vendor_application_page"), payload)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "کد ملی", status_code=400)
        self.assertFalse(VendorApplication.objects.filter(user=self.user).exists())

    def test_pending_application_cannot_be_submitted_twice(self):
        VendorApplication.objects.create(
            user=self.user,
            contact_name="آزمایش فروشنده",
            contact_email="seller@example.com",
            contact_phone="+989121234568",
            national_id="1234567890",
            store_name="فروشگاه آزمایشی",
            seller_type=VendorApplication.SellerType.BOTH,
            description="عرضه محصولات در دسته پوشاک و اکسسوری با تأمین منظم",
        )
        response = self.client.post(reverse("marketplace:vendor_application_page"), self.payload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VendorApplication.objects.filter(user=self.user).count(), 1)

    def test_anonymous_prospect_can_apply_before_account_is_created(self):
        self.client.logout()
        response = self.client.post(reverse("marketplace:vendor_application_page"), self.payload())
        self.assertEqual(response.status_code, 302)
        application = VendorApplication.objects.get(contact_phone="+989121234568")
        self.assertIsNone(application.user)
        self.assertEqual(application.status, VendorApplication.Status.PENDING)
        self.assertEqual(self.client.session.get("vendor_application_id"), application.pk)
