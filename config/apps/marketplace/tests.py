from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import FinancialReconciliation, JournalEntry, LedgerAccount, SettlementBatch, SettlementLine, Shipment, Vendor, VendorOrder, VendorProduct, VendorProductSubmission, WholesalePriceTier
from apps.shop.models import Category, Product
from apps.orders.models import Cart, CartItem, Order, OrderItem
from .payouts import PayoutNotConfigured, submit_settlement_payout
from .carriers import CarrierError, JsonCarrierClient, TipaxClient, validate_quote_input
from .services import (
    account_balance,
    create_daily_settlement_batches,
    get_system_account,
    post_journal,
    record_gateway_settlement,
    record_full_order_refund,
    record_payout_result,
    record_external_reconciliation,
    reverse_journal,
    trial_balance,
    validate_settlement_batch_eligibility,
)


class CarrierSafetyTests(TestCase):
    def test_carrier_label_must_use_https(self):
        client = JsonCarrierClient(
            base_url="https://carrier.example",
            token="test-token",
            shipment_path="/shipments",
        )
        with patch.object(client, "_request", return_value={
            "tracking_number": "TRACK-SAFE-001",
            "label_url": "javascript:alert(1)",
        }):
            with self.assertRaises(CarrierError):
                client.create_shipment({"order_number": "TEST"})

    def test_https_carrier_label_is_accepted(self):
        client = JsonCarrierClient(
            base_url="https://carrier.example",
            token="test-token",
            shipment_path="/shipments",
        )
        with patch.object(client, "_request", return_value={
            "tracking_number": "TRACK-SAFE-002",
            "label_url": "https://labels.carrier.example/label/123",
        }):
            result = client.create_shipment({"order_number": "TEST"})
        self.assertEqual(result["label_url"], "https://labels.carrier.example/label/123")


    def test_carrier_amount_requires_explicit_currency_and_normalizes_rials(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            quote_path="/quote",
        )
        with patch.dict("os.environ", {
            "TIPAX_QUOTE_AMOUNT_PATH": "data.amount",
            "TIPAX_QUOTE_CURRENCY_PATH": "data.currency",
            "TIPAX_AMOUNT_DIVISOR": "10",
        }, clear=True):
            amount = client._amount({"data": {"amount": "1300", "currency": "IRR"}})
        self.assertEqual(amount, 130)

    def test_carrier_amount_without_currency_mapping_fails_closed(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            quote_path="/quote",
        )
        with patch.dict("os.environ", {
            "TIPAX_QUOTE_AMOUNT_PATH": "amount",
            "TIPAX_AMOUNT_DIVISOR": "1",
        }, clear=True):
            with self.assertRaises(CarrierError):
                client._amount({"amount": 130})


    def test_carrier_rejects_nonstandard_rial_divisor(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            quote_path="/quote",
        )
        with patch.dict("os.environ", {
            "TIPAX_QUOTE_AMOUNT_PATH": "amount",
            "TIPAX_QUOTE_CURRENCY_PATH": "currency",
            "TIPAX_AMOUNT_DIVISOR": "100",
        }, clear=True):
            with self.assertRaises(CarrierError):
                client._amount({"amount": "13000", "currency": "IRR"})

    def test_carrier_amount_without_explicit_amount_path_fails_closed(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            quote_path="/quote",
        )
        with patch.dict("os.environ", {
            "TIPAX_AMOUNT_DIVISOR": "1",
            "TIPAX_QUOTE_CURRENCY_PATH": "currency",
        }, clear=True):
            with self.assertRaises(CarrierError):
                client._amount({"amount": 130, "currency": "IRT"})


    def test_final_shipping_quote_requires_valid_postal_codes_and_all_dimensions(self):
        payload = {
            "weight_grams": 500,
            "origin_postal_code": "1234567890",
            "destination_postal_code": "0987654321",
            "length_cm": 20,
            "width_cm": 15,
            "height_cm": 10,
            "declared_value": 100000,
        }
        validated = validate_quote_input(payload)
        self.assertEqual(validated["weight_grams"], 500)
        with self.assertRaises(ValidationError):
            validate_quote_input({**payload, "destination_postal_code": "12345"})
        with self.assertRaises(ValidationError):
            validate_quote_input({key: value for key, value in payload.items() if key != "height_cm"})


    def test_tracking_cost_requires_explicit_currency_and_divisor(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            tracking_path="/track/{tracking_number}",
        )
        with patch.object(client, "_request", return_value={"amount": "1300", "currency": "IRR"}):
            with patch.dict("os.environ", {
                "TIPAX_TRACKING_COST_PATH": "amount",
                "TIPAX_TRACKING_CURRENCY_PATH": "currency",
            }, clear=True):
                with self.assertRaises(CarrierError):
                    client.track("TRACK-1300")

    def test_tracking_rial_cost_normalizes_with_its_own_divisor(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            tracking_path="/track/{tracking_number}",
        )
        with patch.object(client, "_request", return_value={"amount": "1300", "currency": "IRR", "state": "delivered"}):
            with patch.dict("os.environ", {
                "TIPAX_TRACKING_COST_PATH": "amount",
                "TIPAX_TRACKING_CURRENCY_PATH": "currency",
                "TIPAX_TRACKING_AMOUNT_DIVISOR": "10",
                "TIPAX_TRACKING_STATUS_PATH": "state",
            }, clear=True):
                result = client.track("TRACK-1300")
        self.assertEqual(result["actual_cost"], 130)
        self.assertEqual(result["status"], "delivered")

    def test_tracking_cost_rejects_toman_amount_with_rial_divisor(self):
        client = TipaxClient(
            base_url="https://carrier.example",
            token="test-token",
            tracking_path="/track/{tracking_number}",
        )
        with patch.object(client, "_request", return_value={"amount": "130", "currency": "IRT"}):
            with patch.dict("os.environ", {
                "TIPAX_TRACKING_COST_PATH": "amount",
                "TIPAX_TRACKING_CURRENCY_PATH": "currency",
                "TIPAX_TRACKING_AMOUNT_DIVISOR": "10",
            }, clear=True):
                with self.assertRaises(CarrierError):
                    client.track("TRACK-130")


class LedgerPostingTests(TestCase):
    def setUp(self):
        self.clearing = LedgerAccount.objects.create(
            code="test_clearing",
            name="حساب آزمایشی دریافت",
            kind=LedgerAccount.Kind.ASSET,
        )
        self.revenue = LedgerAccount.objects.create(
            code="test_revenue",
            name="درآمد آزمایشی",
            kind=LedgerAccount.Kind.REVENUE,
        )

    def test_posting_is_balanced_and_idempotent(self):
        lines = [
            {"account": self.clearing, "debit": 125000, "credit": 0},
            {"account": self.revenue, "debit": 0, "credit": 125000},
        ]
        entry, created = post_journal(
            idempotency_key="test-payment-001",
            kind="test",
            description="آزمون ثبت دوطرفه",
            lines=lines,
        )
        repeated, created_again = post_journal(
            idempotency_key="test-payment-001",
            kind="test",
            description="تکرار همان درخواست",
            lines=lines,
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(entry.pk, repeated.pk)
        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        self.assertEqual(entry.lines.count(), 2)

    def test_reused_idempotency_key_with_changed_amount_is_rejected(self):
        post_journal(
            idempotency_key="test-fingerprint-001",
            kind="test",
            description="ثبت اولیه",
            lines=[
                {"account": self.clearing, "debit": 1000, "credit": 0},
                {"account": self.revenue, "debit": 0, "credit": 1000},
            ],
        )
        with self.assertRaises(ValidationError):
            post_journal(
                idempotency_key="test-fingerprint-001",
                kind="test",
                description="مبلغ متفاوت با همان کلید",
                lines=[
                    {"account": self.clearing, "debit": 2000, "credit": 0},
                    {"account": self.revenue, "debit": 0, "credit": 2000},
                ],
            )

    def test_reused_key_cannot_be_reassigned_to_another_transaction_kind(self):
        lines = [
            {"account": self.clearing, "debit": 3000, "credit": 0},
            {"account": self.revenue, "debit": 0, "credit": 3000},
        ]
        post_journal(
            idempotency_key="test-kind-fingerprint",
            kind="customer_payment",
            description="پرداخت مشتری",
            lines=lines,
        )
        with self.assertRaises(ValidationError):
            post_journal(
                idempotency_key="test-kind-fingerprint",
                kind="vendor_payout",
                description="واریز فروشنده",
                lines=lines,
            )

    def test_unbalanced_entry_is_rejected(self):
        with self.assertRaises(ValidationError):
            post_journal(
                idempotency_key="test-unbalanced-001",
                kind="test",
                description="سند نامتوازن",
                lines=[
                    {"account": self.clearing, "debit": 100, "credit": 0},
                    {"account": self.revenue, "debit": 0, "credit": 99},
                ],
            )
        self.assertFalse(JournalEntry.objects.filter(idempotency_key="test-unbalanced-001").exists())

    def test_gateway_settlement_records_net_deposit_and_fee(self):
        gateway_clearing = LedgerAccount.objects.create(
            code="gateway_clearing",
            name="وجوه در انتظار تسویه درگاه",
            kind=LedgerAccount.Kind.ASSET,
            currency="IRT",
        )
        customer_funds = LedgerAccount.objects.create(
            code="test_gateway_customer_funds",
            name="وجوه مشتریان در انتظار تسویه",
            kind=LedgerAccount.Kind.LIABILITY,
            currency="IRT",
        )
        post_journal(
            idempotency_key="test-gateway-inflow",
            kind="order_payment",
            description="ورودی آزمایشی درگاه",
            lines=[
                {"account": gateway_clearing, "debit": 100000, "credit": 0},
                {"account": customer_funds, "debit": 0, "credit": 100000},
            ],
        )
        entry, created = record_gateway_settlement(
            settlement_reference="GW-SETTLE-001",
            gross_amount=100000,
            net_amount=99000,
            fee_amount=1000,
            actual_bank_amount=99000,
        )
        self.assertTrue(created)
        self.assertEqual(entry.kind, "gateway_settlement")
        self.assertEqual(entry.lines.count(), 3)
        bank_entry = JournalEntry.objects.get(idempotency_key="bank-deposit:GW-SETTLE-001")
        self.assertEqual(bank_entry.kind, "gateway_bank_deposit")
        reconciliation = FinancialReconciliation.objects.get(
            source=FinancialReconciliation.Source.BANK_STATEMENT,
            external_reference="gateway-settlement:GW-SETTLE-001",
        )
        self.assertEqual(reconciliation.status, FinancialReconciliation.Status.MATCHED)
        report = trial_balance()
        self.assertTrue(report["balanced"])

    def test_gateway_settlement_can_be_reconciled_after_initial_report(self):
        gateway_clearing = LedgerAccount.objects.create(
            code="gateway_clearing",
            name="وجوه در انتظار تسویه درگاه",
            kind=LedgerAccount.Kind.ASSET,
            currency="IRT",
        )
        customer_funds = LedgerAccount.objects.create(
            code="test_gateway_customer_funds",
            name="وجوه مشتریان در انتظار تسویه",
            kind=LedgerAccount.Kind.LIABILITY,
            currency="IRT",
        )
        LedgerAccount.objects.create(
            code="platform_bank",
            name="حساب بانکی پلتفرم",
            kind=LedgerAccount.Kind.ASSET,
            currency="IRT",
        )
        post_journal(
            idempotency_key="test-gateway-inflow-later-reconcile",
            kind="order_payment",
            description="ورودی آزمایشی درگاه",
            lines=[
                {"account": gateway_clearing, "debit": 100000, "credit": 0},
                {"account": customer_funds, "debit": 0, "credit": 100000},
            ],
        )
        first_entry, first_created = record_gateway_settlement(
            settlement_reference="GW-SETTLE-LATER",
            gross_amount=100000,
            net_amount=99000,
            fee_amount=1000,
            actual_bank_amount=None,
        )
        self.assertTrue(first_created)
        self.assertEqual(account_balance(LedgerAccount.objects.get(code="platform_bank")), 0)
        second_entry, second_created = record_gateway_settlement(
            settlement_reference="GW-SETTLE-LATER",
            gross_amount=100000,
            net_amount=99000,
            fee_amount=1000,
            actual_bank_amount=99000,
        )
        self.assertEqual(first_entry.pk, second_entry.pk)
        self.assertTrue(second_created)
        self.assertEqual(account_balance(LedgerAccount.objects.get(code="platform_bank")), 99000)
        reconciliation = FinancialReconciliation.objects.get(
            external_reference="gateway-settlement:GW-SETTLE-LATER",
        )
        self.assertEqual(reconciliation.status, FinancialReconciliation.Status.MATCHED)
        self.assertTrue(trial_balance()["balanced"])

    def test_gateway_bank_shortfall_posts_receivable_and_marks_mismatch(self):
        gateway_clearing = LedgerAccount.objects.create(
            code="gateway_clearing",
            name="وجوه در انتظار تسویه درگاه",
            kind=LedgerAccount.Kind.ASSET,
            currency="IRT",
        )
        customer_funds = LedgerAccount.objects.create(
            code="test_gateway_customer_funds",
            name="وجوه مشتریان در انتظار تسویه",
            kind=LedgerAccount.Kind.LIABILITY,
            currency="IRT",
        )
        post_journal(
            idempotency_key="test-gateway-inflow-shortfall",
            kind="order_payment",
            description="ورودی آزمایشی درگاه",
            lines=[
                {"account": gateway_clearing, "debit": 100000, "credit": 0},
                {"account": customer_funds, "debit": 0, "credit": 100000},
            ],
        )
        record_gateway_settlement(
            settlement_reference="GW-SETTLE-SHORT",
            gross_amount=100000,
            net_amount=99000,
            fee_amount=1000,
            actual_bank_amount=98000,
        )
        reconciliation = FinancialReconciliation.objects.get(
            external_reference="gateway-settlement:GW-SETTLE-SHORT",
        )
        self.assertEqual(reconciliation.status, FinancialReconciliation.Status.MISMATCH)
        receivable = LedgerAccount.objects.get(code="gateway_settlement_receivable")
        self.assertEqual(account_balance(receivable), 1000)
        report = trial_balance()
        self.assertTrue(report["balanced"])

    def test_reversal_preserves_auditable_balanced_history(self):
        entry, _ = post_journal(
            idempotency_key="test-reversal-source",
            kind="test",
            description="سند اصلی",
            lines=[
                {"account": self.clearing, "debit": 1000, "credit": 0},
                {"account": self.revenue, "debit": 0, "credit": 1000},
            ],
        )
        reversal, created = reverse_journal(
            entry=entry,
            idempotency_key="test-reversal",
            reason="آزمون برگشت",
        )
        self.assertTrue(created)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.Status.REVERSED)
        self.assertEqual(reversal.status, JournalEntry.Status.POSTED)
        report = trial_balance()
        self.assertTrue(report["balanced"])
        self.assertEqual(account_balance(self.clearing), 0)
        self.assertEqual(account_balance(self.revenue), 0)


class WholesalePricingValidationTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(phone="+989121234567")
        vendor = Vendor.objects.create(
            user=user,
            store_name="فروشگاه عمده آزمایشی",
            slug="wholesale-test-store",
            status=Vendor.Status.ACTIVE,
        )
        category = Category.objects.create(name="آزمایشی", slug="test-wholesale-category")
        product = Product.objects.create(
            category=category,
            name="محصول آزمایشی",
            slug="test-wholesale-product",
            base_price=1000,
        )
        self.listing = VendorProduct.objects.create(
            vendor=vendor,
            product=product,
            status=VendorProduct.Status.PENDING,
            retail_price=1000,
            stock_quantity=1000,
            weight_grams=100,
            package_length_cm=10,
            package_width_cm=8,
            package_height_cm=4,
            wholesale_enabled=True,
        )

    def test_wholesale_listing_requires_at_least_one_price_tier(self):
        with self.assertRaises(ValidationError) as context:
            self.listing.full_clean()
        self.assertIn("wholesale_enabled", context.exception.message_dict)

    def test_higher_quantity_tier_cannot_be_more_expensive(self):
        WholesalePriceTier.objects.create(
            listing=self.listing,
            minimum_quantity=3,
            unit_price=800,
        )
        tier = WholesalePriceTier(
            listing=self.listing,
            minimum_quantity=10,
            unit_price=700,
        )
        tier.full_clean()
        tier.save()

        invalid_tier = WholesalePriceTier(
            listing=self.listing,
            minimum_quantity=20,
            unit_price=750,
        )
        with self.assertRaises(ValidationError):
            invalid_tier.full_clean()

    def test_cart_uses_wholesale_tier_only_when_wholesale_is_enabled(self):
        WholesalePriceTier.objects.create(
            listing=self.listing,
            minimum_quantity=3,
            unit_price=800,
        )
        WholesalePriceTier.objects.create(
            listing=self.listing,
            minimum_quantity=10,
            unit_price=700,
        )
        self.listing.status = VendorProduct.Status.ACTIVE
        self.listing.save(update_fields=("status", "updated_at"))
        cart = Cart.objects.create(user=self.listing.vendor.user)
        item = CartItem.objects.create(
            cart=cart,
            product=self.listing.product,
            vendor_listing=self.listing,
            quantity=10,
        )
        self.assertEqual(item.unit_price, 700)

        self.listing.wholesale_enabled = False
        self.listing.save(update_fields=("wholesale_enabled", "updated_at"))
        self.assertEqual(item.unit_price, 1000)

    def test_retail_price_cannot_be_lower_than_existing_wholesale_tiers(self):
        WholesalePriceTier.objects.create(
            listing=self.listing,
            minimum_quantity=10,
            unit_price=700,
        )
        self.listing.retail_price = 600
        with self.assertRaises(ValidationError):
            self.listing.full_clean()

    def test_new_product_submission_requires_shipping_dimensions(self):
        submission = VendorProductSubmission(
            vendor=self.listing.vendor,
            category=self.listing.product.category,
            name="محصول بدون ابعاد",
            retail_price=1000,
            weight_grams=0,
            package_length_cm=0,
            package_width_cm=0,
            package_height_cm=0,
        )
        with self.assertRaises(ValidationError) as context:
            submission.clean()
        self.assertIn("weight_grams", context.exception.message_dict)


class VendorShippingSettlementTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        user = get_user_model().objects.create(phone="+989121234568")
        self.vendor = Vendor.objects.create(
            user=user,
            store_name="فروشگاه ارسال مستقل",
            slug="vendor-shipping-settlement-test",
            status=Vendor.Status.ACTIVE,
        )
        self.order = Order.objects.create(
            user=user,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            shipping_title="آدرس",
            shipping_recipient="گیرنده آزمایشی",
            shipping_phone="09120000000",
            shipping_province="تهران",
            shipping_city="تهران",
            shipping_postal_code="1234567890",
            shipping_address="آدرس آزمایشی",
            subtotal=10000,
            discount_amount=0,
            shipping_amount=1000,
            total_amount=11000,
            currency="IRT",
            paid_at=self.now - timedelta(days=3),
        )
        self.vendor_order = VendorOrder.objects.create(
            order=self.order,
            vendor=self.vendor,
            status=VendorOrder.Status.DELIVERED,
            currency="IRT",
            items_snapshot=[{"product_name": "محصول آزمایشی", "quantity": 1}],
            subtotal=10000,
            customer_shipping_amount=1000,
            commission_amount=1000,
            vendor_payable=9000,
            delivered_at=self.now - timedelta(days=2),
            settlement_eligible_at=self.now - timedelta(days=1),
        )
        Shipment.objects.create(
            vendor_order=self.vendor_order,
            provider=Shipment.Provider.MANUAL,
            status=Shipment.Status.DELIVERED,
            payer=Shipment.Payer.VENDOR,
            tracking_number="TRACK-VENDOR-001",
            customer_charge=1000,
            delivered_at=self.now - timedelta(days=2),
        )
        shipping_funds = get_system_account(
            "shipping_funds_payable", "وجوه تخصیص‌یافته به حمل",
            LedgerAccount.Kind.LIABILITY, "IRT",
        )
        clearing = get_system_account(
            "gateway_clearing", "وجوه دریافتی درگاه",
            LedgerAccount.Kind.ASSET, "IRT",
        )
        vendor_payable = get_system_account(
            f"vendor_payable_{self.vendor.pk}",
            f"بستانکاری فروشنده: {self.vendor.store_name}",
            LedgerAccount.Kind.LIABILITY, "IRT", vendor=self.vendor,
        )
        commission = get_system_account(
            "platform_commission", "درآمد کمیسیون پلتفرم",
            LedgerAccount.Kind.REVENUE, "IRT",
        )
        post_journal(
            idempotency_key=f"shipping-test-order-paid:{self.order.uuid}",
            kind="order_payment",
            description="سند اولیه آزمایشی",
            order=self.order,
            lines=[
                {"account": clearing, "debit": 11000, "credit": 0},
                {"account": vendor_payable, "debit": 0, "credit": 9000},
                {"account": commission, "debit": 0, "credit": 1000},
                {"account": shipping_funds, "debit": 0, "credit": 1000},
            ],
        )

    def test_vendor_settlement_hold_cannot_be_shorter_than_24_hours(self):
        self.vendor.settlement_hold_hours = 23
        with self.assertRaises(ValidationError):
            self.vendor.full_clean()

    def test_vendor_paid_shipping_is_included_in_settlement_and_reclassified_once(self):
        batches = create_daily_settlement_batches(now=self.now)
        self.assertEqual(len(batches), 1)
        batch = batches[0]
        self.assertEqual(batch.gross_amount, 10000)
        self.assertEqual(batch.commission_amount, 1000)
        self.assertEqual(batch.shipping_adjustment, 1000)
        self.assertEqual(batch.payable_amount, 10000)
        line = batch.lines.get(vendor_order=self.vendor_order)
        self.assertEqual(line.payable_amount, 10000)
        transfer = JournalEntry.objects.get(
            idempotency_key=f"vendor-shipping-payable:{self.vendor_order.shipments.get().uuid}"
        )
        self.assertEqual(transfer.status, JournalEntry.Status.POSTED)
        self.assertEqual(sum(row.debit for row in transfer.lines.all()), 1000)
        self.assertEqual(sum(row.credit for row in transfer.lines.all()), 1000)
        self.assertEqual(create_daily_settlement_batches(now=self.now), [])

    def test_shipping_allocation_above_customer_charge_holds_settlement(self):
        shipment = self.vendor_order.shipments.get()
        shipment.customer_charge = 1200
        shipment.save(update_fields=("customer_charge", "updated_at"))
        self.assertEqual(create_daily_settlement_batches(now=self.now), [])
        self.assertFalse(SettlementBatch.objects.exists())

    def test_vendor_order_is_not_delivered_until_every_parcel_is_delivered(self):
        from apps.marketplace.tasks import refresh_active_shipments_task

        self.vendor_order.status = VendorOrder.Status.SHIPPED
        self.vendor_order.delivered_at = None
        self.vendor_order.settlement_eligible_at = None
        self.vendor_order.save(update_fields=("status", "delivered_at", "settlement_eligible_at", "updated_at"))
        first = Shipment.objects.create(
            vendor_order=self.vendor_order,
            provider=Shipment.Provider.TIPAX,
            status=Shipment.Status.IN_TRANSIT,
            payer=Shipment.Payer.VENDOR,
            tracking_number="TRACK-PARCEL-A",
            customer_charge=0,
            last_event_at=self.now - timedelta(minutes=2),
        )
        second = Shipment.objects.create(
            vendor_order=self.vendor_order,
            provider=Shipment.Provider.TIPAX,
            status=Shipment.Status.IN_TRANSIT,
            payer=Shipment.Payer.VENDOR,
            tracking_number="TRACK-PARCEL-B",
            customer_charge=0,
            last_event_at=self.now - timedelta(minutes=1),
        )

        with patch("apps.marketplace.carriers.get_carrier") as get_carrier:
            get_carrier.return_value.track.side_effect = lambda tracking: {
                "status": "delivered" if tracking == first.tracking_number else "in_transit",
                "recipient_phone": "09120000000",
            }
            result = refresh_active_shipments_task.run()

        self.assertEqual(result["updated"], 2)
        delivered_parcel = Shipment.objects.get(pk=first.pk)
        self.assertEqual(delivered_parcel.status, Shipment.Status.DELIVERED)
        self.assertEqual(Shipment.objects.get(pk=second.pk).status, Shipment.Status.IN_TRANSIT)
        self.assertNotIn("recipient_phone", delivered_parcel.provider_payload["last_tracking_response"])
        self.vendor_order.refresh_from_db()
        self.assertEqual(self.vendor_order.status, VendorOrder.Status.SHIPPED)
        self.assertIsNone(self.vendor_order.delivered_at)
        self.assertIsNone(self.vendor_order.settlement_eligible_at)

    def test_pending_settlement_is_blocked_if_shipment_later_returns(self):
        batches = create_daily_settlement_batches(now=self.now)
        self.assertEqual(len(batches), 1)
        shipment = self.vendor_order.shipments.get()
        shipment.status = Shipment.Status.RETURNED
        shipment.save(update_fields=("status", "updated_at"))
        self.vendor_order.status = VendorOrder.Status.DISPUTED
        self.vendor_order.save(update_fields=("status", "updated_at"))
        with self.assertRaises(ValidationError):
            validate_settlement_batch_eligibility(batches[0], now=self.now)


    def test_staff_cannot_confirm_delivery_without_auditable_evidence(self):
        staff = get_user_model().objects.create(
            phone="+989121234569",
            is_staff=True,
            is_superuser=True,
        )
        shipment = Shipment.objects.create(
            vendor_order=self.vendor_order,
            provider=Shipment.Provider.MANUAL,
            status=Shipment.Status.IN_TRANSIT,
            payer=Shipment.Payer.VENDOR,
            tracking_number="TRACK-EVIDENCE-001",
            customer_charge=0,
        )
        self.client.force_login(staff)
        url = f"/marketplace/api/admin/shipping/{shipment.uuid}/status/"
        response = self.client.post(
            url,
            data='{"status":"delivered"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, Shipment.Status.IN_TRANSIT)

        response = self.client.post(
            url,
            data='{"status":"delivered","delivery_evidence_reference":"تأیید تحویل در پنل شرکت حمل","delivery_evidence_note":"وضعیت مرسوله با رهگیری شرکت حمل تطبیق داده شد."}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        shipment.refresh_from_db()
        confirmation = shipment.provider_payload["delivery_confirmation"]
        self.assertEqual(confirmation["source"], "staff_manual")
        self.assertEqual(confirmation["reference"], "تأیید تحویل در پنل شرکت حمل")
        self.assertEqual(confirmation["confirmed_by_user_id"], staff.pk)


    def test_delivery_evidence_action_is_available_in_readonly_admin_changelist(self):
        staff = get_user_model().objects.create(
            phone="+989121234570",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(staff)
        response = self.client.get("/admin/marketplace/shipment/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="confirm_delivery_with_evidence"')


class SettlementPayoutSafetyTests(TestCase):
    def setUp(self):
        now = timezone.now()
        user = get_user_model().objects.create(phone="+989121234567")
        self.vendor = Vendor.objects.create(
            user=user,
            store_name="فروشگاه آزمایشی",
            slug="payout-test-store",
            status=Vendor.Status.ACTIVE,
        )
        self.batch = SettlementBatch.objects.create(
            idempotency_key="payout-safety-test",
            vendor=self.vendor,
            status=SettlementBatch.Status.APPROVED,
            period_start=now - timedelta(days=1),
            period_end=now,
            gross_amount=11000,
            commission_amount=1000,
            payable_amount=10000,
        )

    def test_missing_actual_amount_never_marks_batch_paid(self):
        batch = record_payout_result(
            batch_id=self.batch.pk,
            provider_reference="BANK-UNKNOWN-AMOUNT",
            succeeded=True,
            actual_amount=None,
        )
        self.assertEqual(batch.status, SettlementBatch.Status.PROCESSING)
        self.assertEqual(batch.payout_reference, "BANK-UNKNOWN-AMOUNT")
        self.assertFalse(JournalEntry.objects.filter(idempotency_key=f"vendor-payout:{batch.uuid}").exists())

    def test_mismatched_actual_amount_is_reconciled_and_locked(self):
        batch = record_payout_result(
            batch_id=self.batch.pk,
            provider_reference="BANK-WRONG-AMOUNT",
            succeeded=True,
            actual_amount=9900,
        )
        self.assertEqual(batch.status, SettlementBatch.Status.PROCESSING)
        self.assertEqual(batch.payout_reference, "BANK-WRONG-AMOUNT")
        self.assertFalse(JournalEntry.objects.filter(idempotency_key=f"vendor-payout:{batch.uuid}").exists())
        reconciliation = FinancialReconciliation.objects.get(
            source=FinancialReconciliation.Source.BANK_PAYOUT,
            external_reference="payout:BANK-WRONG-AMOUNT:9900",
        )
        self.assertEqual(reconciliation.status, FinancialReconciliation.Status.MISMATCH)

    def test_fractional_bank_amount_is_never_truncated_to_a_successful_payout(self):
        batch = record_payout_result(
            batch_id=self.batch.pk,
            provider_reference="BANK-FRACTIONAL-AMOUNT",
            succeeded=True,
            actual_amount=10000.5,
        )
        self.assertEqual(batch.status, SettlementBatch.Status.PROCESSING)
        self.assertFalse(JournalEntry.objects.filter(idempotency_key=f"vendor-payout:{batch.uuid}").exists())

    def test_matching_confirmed_amount_posts_once_and_marks_paid(self):
        batch = record_payout_result(
            batch_id=self.batch.pk,
            provider_reference="BANK-CORRECT-AMOUNT",
            succeeded=True,
            actual_amount=10000,
        )
        self.assertEqual(batch.status, SettlementBatch.Status.PAID)
        entry = JournalEntry.objects.get(idempotency_key=f"vendor-payout:{batch.uuid}")
        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        reconciliation = FinancialReconciliation.objects.get(
            source=FinancialReconciliation.Source.BANK_PAYOUT,
            external_reference="payout:BANK-CORRECT-AMOUNT:10000",
        )
        self.assertEqual(reconciliation.status, FinancialReconciliation.Status.MATCHED)



    def test_payout_rejects_currency_and_multiplier_mismatch_before_transfer(self):
        env = {
            "PAYOUT_API_BASE_URL": "https://bank.example.test",
            "PAYOUT_API_TOKEN": "test-token",
            "PAYOUT_API_PATH": "/v1/transfers",
            "PAYOUT_AMOUNT_MULTIPLIER": "10",
            "PAYOUT_API_CURRENCY": "IRT",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(PayoutNotConfigured):
                submit_settlement_payout(self.batch.pk)

    def test_payout_preflight_uses_vendor_specific_payable_ledger(self):
        now = timezone.now()
        order = Order.objects.create(
            user=self.vendor.user,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            shipping_title="آدرس",
            shipping_recipient="گیرنده آزمایشی",
            shipping_phone="09120000000",
            shipping_province="تهران",
            shipping_city="تهران",
            shipping_postal_code="1234567890",
            shipping_address="آدرس آزمایشی",
            subtotal=11000,
            discount_amount=0,
            shipping_amount=0,
            total_amount=11000,
            currency=self.batch.currency,
            paid_at=now - timedelta(days=2),
        )
        vendor_order = VendorOrder.objects.create(
            order=order,
            vendor=self.vendor,
            status=VendorOrder.Status.DELIVERED,
            currency=self.batch.currency,
            items_snapshot=[{"product_name": "محصول تسویه", "quantity": 1}],
            subtotal=11000,
            commission_amount=1000,
            vendor_payable=10000,
            delivered_at=now - timedelta(days=2),
            settlement_eligible_at=now - timedelta(hours=1),
        )
        Shipment.objects.create(
            vendor_order=vendor_order,
            provider=Shipment.Provider.MANUAL,
            status=Shipment.Status.DELIVERED,
            payer=Shipment.Payer.VENDOR,
            tracking_number="TRACK-PAYOUT-TEST",
            customer_charge=0,
            delivered_at=now - timedelta(days=2),
        )
        SettlementBatch.objects.filter(pk=self.batch.pk).update(status=SettlementBatch.Status.DRAFT, order_ids=[order.pk])
        self.batch.refresh_from_db()
        SettlementLine.objects.create(
            batch=self.batch,
            vendor_order=vendor_order,
            gross_amount=11000,
            commission_amount=1000,
            payable_amount=10000,
        )
        SettlementBatch.objects.filter(pk=self.batch.pk).update(status=SettlementBatch.Status.APPROVED)

        self.vendor.bank_iban = "IR000000000000000000000000"
        self.vendor.bank_account_name = "فروشگاه آزمایشی"
        self.vendor.save(update_fields=("bank_iban", "bank_account_name"))
        self.vendor.bank_details_verified_at = timezone.now()
        self.vendor.save(update_fields=("bank_details_verified_at",))

        bank = get_system_account(
            "platform_bank", "حساب بانکی پلتفرم", LedgerAccount.Kind.ASSET, currency=self.batch.currency
        )
        vendor_payable = get_system_account(
            f"vendor_payable_{self.vendor.id}",
            f"بستانکاری فروشنده: {self.vendor.store_name}",
            LedgerAccount.Kind.LIABILITY,
            currency=self.batch.currency,
            vendor=self.vendor,
        )
        equity = get_system_account(
            "test_payout_equity", "حساب موازنه تست", LedgerAccount.Kind.EQUITY, currency=self.batch.currency
        )
        post_journal(
            idempotency_key="test-payout-preflight-ledger",
            kind="test_funding",
            description="تأمین مانده تست برای کنترل تسویه",
            lines=[
                {"account": bank, "debit": 100000, "credit": 0},
                {"account": vendor_payable, "debit": 0, "credit": self.batch.payable_amount},
                {"account": equity, "debit": 0, "credit": 100000 - self.batch.payable_amount},
            ],
        )

        env = {
            "PAYOUT_API_BASE_URL": "https://bank.example.test",
            "PAYOUT_API_TOKEN": "test-token",
            "PAYOUT_API_PATH": "/v1/transfers",
            "PAYOUT_AMOUNT_MULTIPLIER": "1",
            "PAYOUT_API_CURRENCY": self.batch.currency,
            "PAYOUT_RESPONSE_AMOUNT_PATH": "amount",
            "PAYOUT_RESPONSE_REFERENCE_PATH": "transfer_id",
            "PAYOUT_RESPONSE_STATUS_PATH": "status",
            "PAYOUT_RESPONSE_CURRENCY_PATH": "currency",
        }
        with patch.dict("os.environ", env), patch("apps.marketplace.payouts.urllib.request.urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = b'{"transfer_id":"BANK-PENDING-TEST","status":"pending","amount":10000,"currency":"IRT"}'
            result = submit_settlement_payout(self.batch.pk)

        self.assertEqual(result.status, SettlementBatch.Status.PROCESSING)
        urlopen.assert_called_once()


class FullRefundInventoryTests(TestCase):
    def setUp(self):
        now = timezone.now()
        user = get_user_model().objects.create(phone="+989121234569")
        category = Category.objects.create(name="آزمون بازپرداخت", slug="refund-test-category")
        product = Product.objects.create(
            category=category,
            name="محصول بازپرداخت",
            slug="refund-test-product",
            base_price=5000,
        )
        self.vendor = Vendor.objects.create(
            user=user,
            store_name="فروشگاه بازپرداخت",
            slug="refund-test-store",
            status=Vendor.Status.ACTIVE,
        )
        self.listing = VendorProduct.objects.create(
            vendor=self.vendor,
            product=product,
            status=VendorProduct.Status.ACTIVE,
            retail_price=5000,
            stock_quantity=4,
            weight_grams=100,
            package_length_cm=10,
            package_width_cm=10,
            package_height_cm=10,
        )
        self.order = Order.objects.create(
            user=user,
            status=Order.Status.PAID,
            payment_status=Order.PaymentStatus.PAID,
            shipping_title="آدرس",
            shipping_recipient="گیرنده آزمایشی",
            shipping_phone="09120000000",
            shipping_province="تهران",
            shipping_city="تهران",
            shipping_postal_code="1234567890",
            shipping_address="آدرس آزمایشی",
            subtotal=10000,
            discount_amount=0,
            shipping_amount=0,
            total_amount=10000,
            currency="IRT",
            paid_at=now,
        )
        OrderItem.objects.create(
            order=self.order,
            product=product,
            vendor_listing=self.listing,
            product_name=product.name,
            unit_price=5000,
            quantity=2,
            line_total=10000,
            vendor_sale_unit_snapshot="عدد",
            vendor_units_per_order_snapshot=1,
        )
        self.vendor_order = VendorOrder.objects.create(
            order=self.order,
            vendor=self.vendor,
            status=VendorOrder.Status.NEW,
            currency="IRT",
            items_snapshot=[{"product_name": product.name, "quantity": 2}],
            subtotal=10000,
            commission_amount=1000,
            vendor_payable=9000,
        )
        clearing = get_system_account(
            "gateway_clearing", "وجوه در انتظار تسویه درگاه", LedgerAccount.Kind.ASSET, "IRT"
        )
        payable = get_system_account(
            f"vendor_payable_{self.vendor.pk}",
            f"بستانکاری فروشنده: {self.vendor.store_name}",
            LedgerAccount.Kind.LIABILITY, "IRT", vendor=self.vendor,
        )
        commission = get_system_account(
            "platform_commission", "درآمد کمیسیون پلتفرم", LedgerAccount.Kind.REVENUE, "IRT"
        )
        post_journal(
            idempotency_key=f"order-paid:{self.order.uuid}",
            kind="order_payment",
            description="سند اصلی فروش برای آزمون بازپرداخت",
            order=self.order,
            lines=[
                {"account": clearing, "debit": 10000, "credit": 0},
                {"account": payable, "debit": 0, "credit": 9000},
                {"account": commission, "debit": 0, "credit": 1000},
            ],
        )

    def test_confirmed_full_refund_restores_stock_once(self):
        entry, created = record_full_order_refund(
            order=self.order,
            refund_reference="REFUND-INVENTORY-001",
            refund_confirmed=True,
            actual_refund_amount=10000,
            refund_source="gateway_clearing",
        )
        self.assertTrue(created)
        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.stock_quantity, 6)

        repeated, created_again = record_full_order_refund(
            order=self.order,
            refund_reference="REFUND-INVENTORY-001",
            refund_confirmed=True,
            actual_refund_amount=10000,
            refund_source="gateway_clearing",
        )
        self.assertFalse(created_again)
        self.assertEqual(repeated.pk, entry.pk)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.stock_quantity, 6)

    def test_refund_is_blocked_after_seller_accepts_order(self):
        self.vendor_order.status = VendorOrder.Status.ACCEPTED
        self.vendor_order.save(update_fields=("status", "updated_at"))
        with self.assertRaises(ValidationError):
            record_full_order_refund(
                order=self.order,
                refund_reference="REFUND-TOO-LATE-001",
                refund_confirmed=True,
                actual_refund_amount=10000,
                refund_source="gateway_clearing",
            )
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.stock_quantity, 4)


class ExternalReconciliationTests(TestCase):
    def test_unmatched_record_can_be_completed_once_actual_amount_arrives(self):
        record, created = record_external_reconciliation(
            source=FinancialReconciliation.Source.BANK_STATEMENT,
            external_reference="BANK-STATEMENT-PENDING-001",
            internal_reference="ORDER-001",
            expected_amount=2500,
            actual_amount=None,
        )
        self.assertTrue(created)
        self.assertEqual(record.status, FinancialReconciliation.Status.UNMATCHED)
        updated, created_again = record_external_reconciliation(
            source=FinancialReconciliation.Source.BANK_STATEMENT,
            external_reference="BANK-STATEMENT-PENDING-001",
            internal_reference="ORDER-001",
            expected_amount=2500,
            actual_amount=2500,
        )
        self.assertFalse(created_again)
        self.assertEqual(updated.pk, record.pk)
        self.assertEqual(updated.status, FinancialReconciliation.Status.MATCHED)

    def test_match_mismatch_and_idempotency(self):
        matched, created = record_external_reconciliation(
            source=FinancialReconciliation.Source.BANK_PAYOUT,
            external_reference="BANK-REF-001",
            internal_reference="SETTLEMENT-1",
            expected_amount=5000,
            actual_amount=5000,
        )
        self.assertTrue(created)
        self.assertEqual(matched.status, FinancialReconciliation.Status.MATCHED)
        repeated, created_again = record_external_reconciliation(
            source=FinancialReconciliation.Source.BANK_PAYOUT,
            external_reference="BANK-REF-001",
            internal_reference="SETTLEMENT-1",
            expected_amount=5000,
            actual_amount=5000,
        )
        self.assertFalse(created_again)
        self.assertEqual(matched.pk, repeated.pk)
        with self.assertRaises(ValidationError):
            record_external_reconciliation(
                source=FinancialReconciliation.Source.BANK_PAYOUT,
                external_reference="BANK-REF-001",
                internal_reference="SETTLEMENT-1",
                expected_amount=5000,
                actual_amount=4900,
            )

        mismatch, _ = record_external_reconciliation(
            source=FinancialReconciliation.Source.CARRIER_INVOICE,
            external_reference="TIPAX-INV-001",
            expected_amount=120000,
            actual_amount=130000,
        )
        self.assertEqual(mismatch.status, FinancialReconciliation.Status.MISMATCH)
