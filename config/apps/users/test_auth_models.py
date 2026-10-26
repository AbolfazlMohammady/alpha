from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Address, City, OTP, Province, User


class UserModelTests(TestCase):
    def test_manager_normalizes_iranian_phone_number(self):
        user = User.objects.create_user(phone="09121234567")
        self.assertEqual(str(user.phone), "+989121234567")

    def test_default_address_is_unique_per_user(self):
        user = User.objects.create_user(phone="09121234567")
        province = Province.objects.get_or_create(name="تهران")[0]
        city = City.objects.get_or_create(province=province, name="تهران")[0]

        Address.objects.create(
            user=user,
            title="خانه",
            phone="09121234567",
            description="تهران",
            city=city,
            postal_code="1234567890",
            is_default=True,
        )

        with self.assertRaises(IntegrityError):
            Address.objects.create(
                user=user,
                title="محل کار",
                phone="09121234567",
                description="تهران",
                city=city,
                postal_code="1234567891",
                is_default=True,
            )




class AddressRecipientTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone="09121111111",
            password="test-password",
            first_name="علی",
            last_name="محمدی",
        )
        self.province = Province.objects.get_or_create(name="تهران")[0]
        self.city = City.objects.get_or_create(province=self.province, name="تهران")[0]

    def _address(self, **kwargs):
        data = {
            "user": self.user,
            "title": "خانه",
            "phone": "+989121111111",
            "description": "آدرس تست",
            "city": self.city,
            "postal_code": "1234567890",
            "is_default": False,
        }
        data.update(kwargs)
        return Address(**data)

    def test_own_address_uses_profile_name(self):
        address = self._address()
        address.full_clean()
        self.assertFalse(address.is_for_other)
        self.assertEqual(address.recipient_name, "")
        self.assertEqual(address.recipient_display_name, "علی محمدی")

    def test_other_address_requires_recipient_name(self):
        address = self._address(is_for_other=True)
        with self.assertRaises(ValidationError):
            address.full_clean()

    def test_other_address_uses_saved_recipient_name(self):
        address = self._address(is_for_other=True, recipient_name="رضا محمدی")
        address.full_clean()
        self.assertEqual(address.recipient_display_name, "رضا محمدی")

    def test_turning_off_other_recipient_clears_saved_name(self):
        address = self._address(is_for_other=True, recipient_name="رضا محمدی")
        address.is_for_other = False
        address.full_clean()
        self.assertEqual(address.recipient_name, "")
        self.assertEqual(address.recipient_display_name, "علی محمدی")



class OTPVerificationTests(TestCase):
    def test_successful_otp_is_deleted_and_plaintext_code_is_not_stored(self):
        phone = "+989121234567"
        otp = OTP.objects.create(
            phone=phone,
            code=make_password("123456"),
            expire_at=timezone.now() + timedelta(minutes=2),
        )
        session = self.client.session
        session["otp_phone"] = phone
        session["otp_id"] = otp.id
        session.save()

        response = self.client.post(
            reverse("users:verify_otp"),
            {"code": "123456"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(OTP.objects.filter(pk=otp.pk).exists())
        user = User.objects.get(phone=phone)
        self.assertTrue(user.is_active)

    def test_expired_otp_is_deleted(self):
        phone = "+989121234568"
        otp = OTP.objects.create(
            phone=phone,
            code=make_password("123456"),
            expire_at=timezone.now() - timedelta(minutes=1),
        )
        session = self.client.session
        session["otp_phone"] = phone
        session["otp_id"] = otp.id
        session.save()

        response = self.client.post(
            reverse("users:verify_otp"),
            {"code": "123456"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(OTP.objects.filter(pk=otp.pk).exists())



    def test_fifth_wrong_otp_attempt_deletes_challenge(self):
        phone = "+989121234569"
        otp = OTP.objects.create(
            phone=phone,
            code=make_password("123456"),
            expire_at=timezone.now() + timedelta(minutes=2),
        )
        session = self.client.session
        session["otp_phone"] = phone
        session["otp_id"] = otp.id
        session.save()

        for _ in range(5):
            response = self.client.post(
                reverse("users:verify_otp"),
                {"code": "000000"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(OTP.objects.filter(pk=otp.pk).exists())
