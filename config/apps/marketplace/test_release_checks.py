"""Focused release smoke tests for marketplace, logistics, and accounting.

These tests use mocked carrier responses only. They never call a real carrier or bank API.
Run with: python manage.py test apps.marketplace.test_release_checks
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .carriers import CarrierNotConfigured, TipaxClient, validate_quote_input
from .models import JournalEntry, LedgerAccount, SettlementBatch, Vendor, VendorApplication, VendorOrder, VendorProduct, WholesalePriceTier, Shipment
from apps.users.models import RoleUser
from apps.shop.models import Category, Product
from apps.orders.models import Order
from .services import post_journal, trial_balance


class LogisticsReleaseChecks(TestCase):
    def valid_quote_payload(self):
        return {
            "weight_grams": 750,
            "origin_postal_code": "1234567891",
            "destination_postal_code": "0987654321",
            "length_cm": 25,
            "width_cm": 18,
            "height_cm": 12,
            "declared_value": 250000,
        }

    def test_quote_input_accepts_complete_iranian_parcel(self):
        result = validate_quote_input(self.valid_quote_payload())
        self.assertEqual(result["weight_grams"], 750)
        self.assertEqual(result["origin_postal_code"], "1234567891")
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
    def test_store_manager_without_vendor_row_gets_active_vendor_profile(self):
        user = get_user_model().objects.create_user(
            phone="+989121234567",
            role=RoleUser.STORE_MANAGER,
            first_name="فروشگاه آزمایشی",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("marketplace:vendor_dashboard_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پنل فروشنده")
        self.assertContains(response, 'href="/marketplace/store/"')
        self.assertContains(response, 'href="/marketplace/vendor/dashboard/#vd-orders-section"')
        self.assertNotContains(response, 'href="/control/products/"')
        self.assertNotContains(response, 'href="/control/"')
        vendor = Vendor.objects.get(user=user)
        self.assertEqual(vendor.status, Vendor.Status.ACTIVE)
        self.assertIsNotNone(vendor.approved_at)
        self.assertTrue(vendor.slug.startswith(f"store-{user.pk}-"))

    def test_existing_pending_vendor_activates_after_manual_role_assignment(self):
        user = get_user_model().objects.create_user(
            phone="+989121234571",
            role=RoleUser.STORE_MANAGER,
        )
        Vendor.objects.create(
            user=user,
            store_name="فروشگاه در انتظار",
            slug="pending-role-activation-test",
            status=Vendor.Status.PENDING,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:vendor_dashboard_page"))
        self.assertEqual(response.status_code, 200)
        vendor = Vendor.objects.get(user=user)
        self.assertEqual(vendor.status, Vendor.Status.ACTIVE)
        self.assertIsNotNone(vendor.approved_at)

    def test_approved_application_configures_vendor_store_name_and_seller_type(self):
        user = get_user_model().objects.create_user(
            phone="+989121234575",
            email="wholesale@example.com",
            role=RoleUser.STORE_MANAGER,
        )
        VendorApplication.objects.create(
            user=user,
            contact_name="متقاضی عمده",
            contact_email="wholesale@example.com",
            contact_phone="+989121234575",
            national_id="1234567891",
            store_name="عمده‌فروشی نمونه",
            seller_type=VendorApplication.SellerType.WHOLESALE,
            description="تأمین عمده محصولات با موجودی منظم",
            status=VendorApplication.Status.APPROVED,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:vendor_dashboard_page"))
        self.assertEqual(response.status_code, 200)
        vendor = Vendor.objects.get(user=user)
        self.assertEqual(vendor.store_name, "عمده‌فروشی نمونه")
        self.assertEqual(vendor.seller_type, Vendor.SellerType.WHOLESALE)

    def test_rejected_application_blocks_seller_access_even_if_role_is_assigned(self):
        user = get_user_model().objects.create_user(
            phone="+989121234580",
            email="rejected@example.com",
            role=RoleUser.STORE_MANAGER,
        )
        VendorApplication.objects.create(
            user=user,
            contact_name="متقاضی ردشده",
            contact_email="rejected@example.com",
            contact_phone="+989121234580",
            national_id="1234567891",
            store_name="فروشگاه ردشده",
            seller_type=VendorApplication.SellerType.RETAIL,
            description="درخواست آزمایشی برای بررسی دسترسی",
            status=VendorApplication.Status.REJECTED,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:vendor_dashboard_page"))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Vendor.objects.filter(user=user).exists())

    def test_customer_role_cannot_access_existing_vendor_profile(self):
        user = get_user_model().objects.create_user(
            phone="+989121234573",
            role=RoleUser.CUSTOMER,
        )
        Vendor.objects.create(
            user=user,
            store_name="فروشگاه بدون نقش",
            slug="customer-vendor-denied-test",
            status=Vendor.Status.ACTIVE,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:vendor_dashboard_page"))
        self.assertEqual(response.status_code, 403)

    def test_suspended_vendor_is_not_silently_reactivated(self):
        user = get_user_model().objects.create_user(
            phone="+989121234572",
            role=RoleUser.STORE_MANAGER,
        )
        Vendor.objects.create(
            user=user,
            store_name="فروشگاه تعلیق‌شده",
            slug="suspended-role-activation-test",
            status=Vendor.Status.SUSPENDED,
        )
        self.client.force_login(user)
        self.client.get(reverse("marketplace:vendor_dashboard_page"))
        self.assertEqual(Vendor.objects.get(user=user).status, Vendor.Status.SUSPENDED)




class PortalPlaceholderAccessTests(TestCase):
    def test_homepage_renders_seller_shortcuts_for_store_manager(self):
        user = get_user_model().objects.create_user(
            phone="+989121234581",
            role=RoleUser.STORE_MANAGER,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("home:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پنل فروشنده")
        self.assertContains(response, "new-product")

    def test_homepage_renders_admin_shortcuts_for_staff(self):
        user = get_user_model().objects.create_user(
            phone="+989121234582",
            role=RoleUser.ADMIN,
            is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("home:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مدیریت و حسابداری")
        self.assertContains(response, "trial-balance")

    def test_store_manager_can_open_seller_placeholder(self):
        user = get_user_model().objects.create_user(phone="+989121234576", role=RoleUser.STORE_MANAGER)
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:portal_section_page", args=["new-product"]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("marketplace:vendor_dashboard_page"), response["Location"])
        self.assertIn("#vd-new-product-section", response["Location"])

    def test_customer_cannot_open_seller_placeholder(self):
        user = get_user_model().objects.create_user(phone="+989121234577", role=RoleUser.CUSTOMER)
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:portal_section_page", args=["new-product"]))
        self.assertEqual(response.status_code, 403)

    def test_non_staff_cannot_open_admin_placeholder(self):
        user = get_user_model().objects.create_user(phone="+989121234578", role=RoleUser.STORE_MANAGER)
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:portal_section_page", args=["trial-balance"]))
        self.assertEqual(response.status_code, 403)


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
            "national_id": "1234567891",
            "store_name": "فروشگاه آزمایشی",
            "seller_type": "both",
            "province": "تهران",
            "city": "تهران",
            "postal_code": "1234567891",
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
        for national_id in ("123", "1234567890", "1111111111"):
            with self.subTest(national_id=national_id):
                payload = self.payload()
                payload["national_id"] = national_id
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
            national_id="1234567891",
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



class VendorSettlementDashboardTests(TestCase):
    def test_matured_unbatched_delivered_order_is_in_pending_settlement_total(self):
        user = get_user_model().objects.create_user(
            phone="+989121234574",
            role=RoleUser.STORE_MANAGER,
        )
        vendor = Vendor.objects.create(
            user=user,
            store_name="فروشگاه تسویه",
            slug="settlement-dashboard-test",
            status=Vendor.Status.ACTIVE,
        )
        order = Order.objects.create(
            user=user,
            shipping_title="خانه",
            shipping_recipient="گیرنده آزمایشی",
            shipping_phone="+989121234574",
            shipping_province="تهران",
            shipping_city="تهران",
            shipping_postal_code="1234567891",
            shipping_address="نشانی آزمایشی",
            subtotal=1000,
            total_amount=1000,
        )
        vendor_order = VendorOrder.objects.create(
            order=order,
            vendor=vendor,
            status=VendorOrder.Status.DELIVERED,
            items_snapshot=[{"vendor_product_id": 77, "product_name": "محصول"}],
            subtotal=1000,
            customer_shipping_amount=200,
            commission_amount=100,
            vendor_payable=900,
            delivered_at=timezone.now() - timedelta(days=2),
            settlement_eligible_at=timezone.now() - timedelta(days=1),
        )
        Shipment.objects.create(
            vendor_order=vendor_order,
            provider=Shipment.Provider.MANUAL,
            status=Shipment.Status.DELIVERED,
            payer=Shipment.Payer.VENDOR,
            tracking_number="TRACK-TEST-1",
            customer_charge=200,
            actual_cost=200,
            delivered_at=timezone.now() - timedelta(days=2),
        )
        self.client.force_login(user)
        response = self.client.get(reverse("marketplace:vendor_dashboard_api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settlement"]["pending_amount"], 1100)


class VendorProductArchiveTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            phone="+989121234569",
            role=RoleUser.STORE_MANAGER,
        )
        self.vendor = Vendor.objects.create(
            user=self.user,
            store_name="فروشگاه آرشیو",
            slug="archive-store-test",
            status=Vendor.Status.ACTIVE,
        )
        category = Category.objects.create(name="آزمایش", slug="archive-test-category")
        product = Product.objects.create(
            category=category,
            name="محصول آزمایشی",
            slug="archive-test-product",
            base_price=1000,
            marketplace_only=True,
        )
        self.listing = VendorProduct.objects.create(
            vendor=self.vendor,
            product=product,
            status=VendorProduct.Status.ACTIVE,
            retail_price=1000,
            stock_quantity=5,
            weight_grams=500,
            package_length_cm=10,
            package_width_cm=10,
            package_height_cm=10,
        )
        self.client.force_login(self.user)

    def test_retail_only_seller_cannot_create_wholesale_tier_via_api(self):
        response = self.client.post(
            reverse("marketplace:vendor_wholesale_tier_api", args=[self.listing.pk]),
            data='{"minimum_quantity": 2, "unit_price": 800}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(WholesalePriceTier.objects.filter(listing=self.listing).exists())

    def test_retail_only_seller_cannot_create_wholesale_tier(self):
        tier = WholesalePriceTier(
            listing=self.listing,
            minimum_quantity=2,
            unit_price=800,
        )
        with self.assertRaises(ValidationError):
            tier.full_clean()

    def test_archive_keeps_listing_record_and_zeroes_stock(self):
        response = self.client.post(
            reverse("marketplace:vendor_product_archive_api", args=[self.listing.pk]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, VendorProduct.Status.PAUSED)
        self.assertEqual(self.listing.stock_quantity, 0)
        self.assertTrue(Product.objects.filter(pk=self.listing.product_id).exists())

    def test_archive_is_blocked_while_listing_has_open_vendor_order(self):
        order = Order.objects.create(
            user=self.user,
            shipping_title="خانه",
            shipping_recipient="گیرنده آزمایشی",
            shipping_phone="+989121234569",
            shipping_province="تهران",
            shipping_city="تهران",
            shipping_postal_code="1234567891",
            shipping_address="نشانی آزمایشی",
            subtotal=1000,
            total_amount=1000,
        )
        VendorOrder.objects.create(
            order=order,
            vendor=self.vendor,
            status=VendorOrder.Status.PREPARING,
            items_snapshot=[{"vendor_product_id": self.listing.pk, "product_name": "محصول آزمایشی"}],
            subtotal=1000,
            commission_amount=100,
            vendor_payable=900,
        )
        response = self.client.post(
            reverse("marketplace:vendor_product_archive_api", args=[self.listing.pk]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, VendorProduct.Status.ACTIVE)
        self.assertEqual(self.listing.stock_quantity, 5)

    def test_seller_cannot_archive_another_vendors_listing(self):
        other_user = get_user_model().objects.create_user(
            phone="+989121234570",
            role=RoleUser.STORE_MANAGER,
        )
        self.client.force_login(other_user)
        response = self.client.post(
            reverse("marketplace:vendor_product_archive_api", args=[self.listing.pk]),
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, VendorProduct.Status.ACTIVE)


class AccountingJournalApiTests(TestCase):
    def setUp(self):
        self.cash = LedgerAccount.objects.create(
            code="journal_api_test_cash",
            name="وجه نقد تست API",
            kind=LedgerAccount.Kind.ASSET,
            currency="IRT",
        )
        self.revenue = LedgerAccount.objects.create(
            code="journal_api_test_revenue",
            name="درآمد تست API",
            kind=LedgerAccount.Kind.REVENUE,
            currency="IRT",
        )

    def test_staff_can_inspect_posted_journal_entries_and_lines(self):
        post_journal(
            idempotency_key="release-journal-inspection-001",
            kind="release_smoke",
            description="ثبت فروش آزمایشی",
            lines=[
                {"account": self.cash, "debit": 75000, "credit": 0},
                {"account": self.revenue, "debit": 0, "credit": 75000},
            ],
        )
        staff = get_user_model().objects.create_user(
            phone="+989120000701",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get("/marketplace/api/admin/accounting/journal-entries/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        entry = next(row for row in payload["results"] if row["kind"] == "release_smoke")
        self.assertEqual(entry["description"], "ثبت فروش آزمایشی")
        self.assertEqual(entry["debit_total"], 75000)
        self.assertEqual(entry["credit_total"], 75000)
        self.assertEqual(len(entry["lines"]), 2)

    def test_non_staff_cannot_inspect_journal_entries(self):
        user = get_user_model().objects.create_user(
            phone="+989120000702",
            password="test-password",
        )
        self.client.force_login(user)
        response = self.client.get("/marketplace/api/admin/accounting/journal-entries/")
        self.assertEqual(response.status_code, 302)


class SettlementHistoryApiTests(TestCase):
    def test_staff_can_see_failed_and_paid_settlements_not_only_pending_approval(self):
        vendor_user = get_user_model().objects.create_user(
            phone="+989120000703",
            password="test-password",
            role=RoleUser.STORE_MANAGER,
        )
        vendor = Vendor.objects.create(
            user=vendor_user,
            store_name="فروشگاه سابقه تسویه",
            slug="settlement-history-api-test",
            status=Vendor.Status.ACTIVE,
        )
        now = timezone.now()
        SettlementBatch.objects.create(
            idempotency_key="settlement-history-failed-001",
            vendor=vendor,
            status=SettlementBatch.Status.FAILED,
            period_start=now - timedelta(days=2),
            period_end=now - timedelta(days=1),
            gross_amount=100000,
            commission_amount=10000,
            payable_amount=90000,
            failure_reason="خطای آزمایشی پرداخت",
        )
        SettlementBatch.objects.create(
            idempotency_key="settlement-history-paid-001",
            vendor=vendor,
            status=SettlementBatch.Status.PAID,
            period_start=now - timedelta(days=4),
            period_end=now - timedelta(days=3),
            gross_amount=200000,
            commission_amount=20000,
            payable_amount=180000,
            paid_at=now,
            payout_reference="bank-test-123",
        )
        staff = get_user_model().objects.create_user(
            phone="+989120000704",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get("/marketplace/api/admin/settlements/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["results"]
        self.assertEqual({row["status"] for row in rows}, {"failed", "paid"})
        failed = next(row for row in rows if row["status"] == "failed")
        self.assertEqual(failed["failure_reason"], "خطای آزمایشی پرداخت")
        paid = next(row for row in rows if row["status"] == "paid")
        self.assertEqual(paid["payout_reference"], "bank-test-123")


class VendorSalesAnalyticsTests(TestCase):
    def test_sales_report_distinguishes_sellable_packs_from_physical_items(self):
        user = get_user_model().objects.create_user(
            phone="+989120000705",
            password="test-password",
            role=RoleUser.STORE_MANAGER,
        )
        vendor = Vendor.objects.create(
            user=user,
            store_name="فروشگاه تحلیل فروش",
            slug="vendor-sales-analytics-test",
            status=Vendor.Status.ACTIVE,
        )
        order = Order.objects.create(
            user=user,
            shipping_title="خانه",
            shipping_recipient="گیرنده آزمایشی",
            shipping_phone="+989120000705",
            shipping_province="تهران",
            shipping_city="تهران",
            shipping_postal_code="1234567891",
            shipping_address="نشانی آزمایشی",
            subtotal=200000,
            total_amount=200000,
        )
        VendorOrder.objects.create(
            order=order,
            vendor=vendor,
            status=VendorOrder.Status.DELIVERED,
            items_snapshot=[{
                "vendor_product_id": 42,
                "product_name": "شلوار جین",
                "quantity": 2,
                "sale_unit": "جین",
                "units_per_order": 12,
                "line_total": 200000,
            }],
            subtotal=200000,
            commission_amount=20000,
            vendor_payable=180000,
        )
        self.client.force_login(user)
        response = self.client.get("/marketplace/api/vendor/dashboard/")
        self.assertEqual(response.status_code, 200)
        sales = response.json()["sales"]
        self.assertEqual(sales["sold_units_last_30_days"], 2)
        self.assertEqual(sales["physical_units_last_30_days"], 24)
        self.assertEqual(sales["top_products"][0]["sale_unit"], "جین")
        self.assertEqual(sales["top_products"][0]["physical_units"], 24)
