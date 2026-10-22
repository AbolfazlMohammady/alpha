from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import FinancialReconciliation, JournalEntry, LedgerAccount
from .services import (
    account_balance,
    post_journal,
    record_external_reconciliation,
    reverse_journal,
    trial_balance,
)


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


class ExternalReconciliationTests(TestCase):
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
