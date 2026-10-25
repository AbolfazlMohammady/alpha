from decimal import Decimal

from django.test import SimpleTestCase

from .services import _strict_quantity


class StrictQuantityTests(SimpleTestCase):
    def test_rejects_fractional_decimal_quantity(self):
        with self.assertRaises(ValueError):
            _strict_quantity(Decimal("1.5"))

    def test_rejects_non_finite_decimal_quantity(self):
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _strict_quantity(value)

    def test_accepts_integral_decimal_quantity(self):
        self.assertEqual(_strict_quantity(Decimal("12.0")), 12)
