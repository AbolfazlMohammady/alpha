from django import forms
from django.db.models import Q
from django.utils.text import slugify

from apps.shop.models import Category, ContactPageSettings, Product, ProductColor, ProductImage, ProductSize, ProductVariant
from apps.customizer.models import Artwork, CustomizerPricingSettings
from apps.users.models import User, RoleUser
from apps.orders.models import Order


class ControlFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "cc-input")


class UserForm(ControlFormMixin, forms.ModelForm):
    phone = forms.CharField(
        label="شماره تلفن",
        required=True,
        widget=forms.TextInput(attrs={
            "inputmode": "tel",
            "dir": "ltr",
            "autocomplete": "tel",
            "placeholder": "0912 123 4567",
        }),
    )

    class Meta:
        model = User
        fields = (
            "first_name", "last_name", "phone", "email",
            "role", "gender", "birth_date", "image", "is_active",
        )
        widgets = {
            "phone": forms.TextInput(attrs={
                "inputmode": "tel",
                "dir": "ltr",
                "autocomplete": "tel",
                "placeholder": "0912 123 4567",
            }),
            "birth_date": forms.HiddenInput(attrs={
                "data-gregorian-input": "1",
            }),
            "image": forms.ClearableFileInput(),
        }

    def clean_phone(self):
        raw = str(self.cleaned_data.get("phone") or "").strip()
        if not raw:
            raise forms.ValidationError("شماره تلفن را وارد کنید.")

        # Accept Persian digits, then use the same Iran-aware normalizer
        # used by the authentication manager.
        raw = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        # Normalize every accepted national form (0912...) to E.164
        # before it reaches the model. This guarantees the +98 prefix is
        # persisted even when the operator enters a local Iranian number.
        if raw.startswith("0098"):
            raw = "+" + raw[2:]
        elif raw.startswith("98"):
            raw = "+" + raw
        elif raw.startswith("0"):
            raw = "+98" + raw[1:]

        try:
            phone = User.objects.normalize_phone(raw)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

        if getattr(phone, "country_code", None) != 98:
            raise forms.ValidationError("شماره تلفن باید با پیش‌شماره ایران (+98) باشد.")

        # PhoneNumberField defaults to E.164 in the database. Returning the
        # explicit E.164 value here also makes the storage contract obvious.
        return phone.as_e164

    def clean_birth_date(self):
        birth_date = self.cleaned_data.get("birth_date")
        if not birth_date:
            return None

        from datetime import date
        from django.utils import timezone

        today = timezone.localdate()
        try:
            minimum_birth_date = date(today.year - 13, today.month, today.day)
        except ValueError:
            minimum_birth_date = date(today.year - 13, 2, 28)

        if birth_date >= today:
            raise forms.ValidationError("تاریخ تولد باید قبل از امروز باشد.")
        if birth_date > minimum_birth_date:
            raise forms.ValidationError("سن کاربر هنگام ثبت باید حداقل ۱۳ سال باشد.")
        return birth_date

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.role != RoleUser.CUSTOMER
        if user.role == RoleUser.ADMIN:
            user.is_staff = True
        if commit:
            user.save()
        return user



class CategoryForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "slug", "description", "image", "is_active", "sort_order", "seo_title", "seo_description")


class ProductForm(ControlFormMixin, forms.ModelForm):
    discount_percent = forms.IntegerField(
        label="درصد تخفیف", min_value=0, max_value=100, required=False, initial=0,
        widget=forms.NumberInput(attrs={"min": "0", "max": "100", "step": "1", "inputmode": "numeric"}),
    )

    class Meta:
        model = Product
        fields = (
            "name", "category", "slug", "short_description", "description",
            "base_price", "compare_at_price", "is_active", "is_featured",
            "seo_title", "seo_description",
        )
        labels = {"base_price": "قیمت قبل از تخفیف", "compare_at_price": "قیمت نهایی"}
        widgets = {
            "compare_at_price": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        compare_price = self.instance.compare_at_price if self.instance and self.instance.pk else None
        current_price = self.instance.base_price if self.instance and self.instance.pk else None
        if compare_price and current_price and compare_price > current_price:
            self.initial["discount_percent"] = round((compare_price - current_price) * 100 / compare_price)
            self.initial["base_price"] = compare_price
        else:
            self.initial["discount_percent"] = 0
        self.fields["base_price"].widget.attrs.update({
            "inputmode": "numeric", "min": "0", "data-price-before-discount": "1"
        })

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip()
        if not slug:
            slug = slugify(self.cleaned_data.get("name", ""), allow_unicode=True)
        return slug

    def clean(self):
        cleaned = super().clean()
        before = cleaned.get("base_price") or 0
        discount = cleaned.get("discount_percent") or 0
        cleaned["compare_at_price"] = before if discount > 0 else None
        cleaned["base_price"] = round(before * (100 - discount) / 100)
        return cleaned


class CustomizerPricingForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = CustomizerPricingSettings
        fields = ("tshirt_base_price", "customer_label_price")
        labels = {
            "tshirt_base_price": "قیمت پایه تیشرت در استودیو سه‌بعدی",
            "customer_label_price": "قیمت هر لیبل آپلودی مشتری",
        }
        widgets = {
            "tshirt_base_price": forms.NumberInput(
                attrs={"min": "0", "inputmode": "numeric", "placeholder": "مثلاً 1000000"}
            ),
            "customer_label_price": forms.NumberInput(
                attrs={"min": "0", "inputmode": "numeric", "placeholder": "مثلاً 100000"}
            ),
        }

    def clean_tshirt_base_price(self):
        value = self.cleaned_data.get("tshirt_base_price")
        if value is None or value < 0:
            raise forms.ValidationError("قیمت پایه تیشرت نمی‌تواند منفی باشد.")
        return value

    def clean_customer_label_price(self):
        value = self.cleaned_data.get("customer_label_price")
        if value is None or value < 0:
            raise forms.ValidationError("قیمت لیبل مشتری نمی‌تواند منفی باشد.")
        return value


class ArtworkForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = Artwork
        fields = ("name", "slug", "image", "base_price", "min_width_px", "is_active")
        labels = {
            "name": "نام لیبل",
            "slug": "شناسه فنی",
            "image": "تصویر لیبل",
            "base_price": "قیمت پایه",
            "min_width_px": "حداقل عرض فایل",
            "is_active": "فعال",
        }
        widgets = {
            "image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "base_price": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
            "min_width_px": forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["image"].required = not bool(self.instance and self.instance.pk)

    def clean_slug(self):
        value = (self.cleaned_data.get("slug") or "").strip()
        if not value:
            value = slugify(self.cleaned_data.get("name", ""), allow_unicode=True)
        return value


class ProductColorForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = ProductColor
        fields = ("name", "slug", "hex_code", "is_active")
        labels = {
            "name": "نام رنگ",
            "slug": "شناسه رنگ",
            "hex_code": "کد رنگ",
            "is_active": "فعال",
        }
        widgets = {
            "hex_code": forms.TextInput(attrs={"type": "color", "class": "cc-color-picker"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False

    def clean_slug(self):
        return slugify(
            self.cleaned_data.get("slug") or self.cleaned_data.get("name", ""),
            allow_unicode=True,
        )


class ProductImageForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ("image", "alt_text", "image_type", "sort_order")
        labels = {
            "image": "تصویر",
            "alt_text": "متن جایگزین",
            "image_type": "نوع تصویر",
            "sort_order": "ترتیب",
        }
        widgets = {
            "image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "sort_order": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
        }


class ProductVariantForm(ControlFormMixin, forms.ModelForm):
    discount_percent = forms.IntegerField(
        label="درصد تخفیف",
        min_value=0,
        max_value=100,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={"min": "0", "max": "100", "step": "1", "inputmode": "numeric"}),
    )

    class Meta:
        model = ProductVariant
        fields = (
            "color", "size", "sku", "use_product_price", "price",
            "compare_at_price", "stock_quantity", "is_active",
        )
        labels = {
            "color": "رنگ",
            "size": "سایز",
            "sku": "SKU",
            "use_product_price": "استفاده از قیمت محصول",
            "price": "قیمت اختصاصی",
            "compare_at_price": "قیمت نهایی",
            "stock_quantity": "موجودی",
            "is_active": "فعال",
        }
        widgets = {
            "compare_at_price": forms.HiddenInput(),
            "use_product_price": forms.CheckboxInput(attrs={"class": "cc-variant-inherit-price"}),
            "stock_quantity": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
        }

    def __init__(self, *args, product=None, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)

        # Sizes are global catalog options (S/M/L/XL by default) and must
        # always be available in the empty form used by the JS multi-select.
        self.fields["size"].queryset = ProductSize.objects.filter(
            is_active=True
        ).order_by("sort_order", "name")

        # ProductColor is a catalog-level model. New variants can use any
        # active global color; legacy product-specific colors remain available.
        current_color_id = self.instance.color_id if self.instance and self.instance.pk else None
        color_filter = Q(product__isnull=True)
        if product is not None:
            color_filter |= Q(product=product)
        if current_color_id:
            color_filter |= Q(pk=current_color_id)
        self.fields["color"].queryset = ProductColor.objects.filter(
            color_filter,
            is_active=True,
        ).distinct().order_by("name")

        self.fields["sku"].required = False
        self.fields["price"].required = False
        self.fields["price"].widget.attrs.update({
            "min": "0", "inputmode": "numeric", "data-variant-before": "1"
        })

        if self.instance and self.instance.pk:
            self.initial["use_product_price"] = self.instance.use_product_price
            current = self.instance.price
            compare = self.instance.compare_at_price
            if not self.instance.use_product_price and compare and current and compare > current:
                self.initial["discount_percent"] = round((compare - current) * 100 / compare)
                self.initial["price"] = compare
            else:
                self.initial["discount_percent"] = 0
        else:
            self.initial["use_product_price"] = True
            self.initial["discount_percent"] = 0

    def clean(self):
        cleaned = super().clean()

        if self.instance.pk and not self.has_changed():
            cleaned["price"] = self.instance.price
            cleaned["compare_at_price"] = self.instance.compare_at_price
            cleaned["sku"] = self.instance.sku
            cleaned["use_product_price"] = self.instance.use_product_price
            return cleaned

        if not self.instance.pk and not self.has_changed():
            return cleaned

        use_product_price = cleaned.get("use_product_price", True)
        if use_product_price:
            if not self.product:
                self.add_error("price", "ابتدا محصول را ذخیره کنید.")
                return cleaned
            cleaned["price"] = self.product.base_price
            cleaned["compare_at_price"] = None
            cleaned["discount_percent"] = 0
        else:
            before = cleaned.get("price")
            if before in (None, ""):
                self.add_error("price", "برای قیمت اختصاصی، قیمت را وارد کنید.")
                return cleaned
            before = int(before)
            discount = cleaned.get("discount_percent") or 0
            cleaned["compare_at_price"] = before if discount > 0 else None
            cleaned["price"] = round(before * (100 - discount) / 100)

        if not cleaned.get("sku"):
            import uuid
            cleaned["sku"] = f"BAB-{uuid.uuid4().hex[:10].upper()}"

        return cleaned


class ProductColorFormSetMixin:
    pass


class ProductSizeForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = ProductSize
        fields = ("name", "slug", "sort_order", "is_active")
        labels = {
            "name": "نام سایز",
            "slug": "شناسه سایز",
            "sort_order": "ترتیب نمایش",
            "is_active": "فعال",
        }
        widgets = {
            "sort_order": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False

    def clean_slug(self):
        return slugify(
            self.cleaned_data.get("slug") or self.cleaned_data.get("name", ""),
            allow_unicode=True,
        )




class OrderWorkflowActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=(
            ("preparing", "آماده‌سازی برای ارسال"),
            ("shipped", "ثبت ارسال"),
            ("delivered", "ثبت تحویل"),
        ),
        widget=forms.HiddenInput(),
    )


class ContactPageSettingsForm(ControlFormMixin, forms.ModelForm):
    class Meta:
        model = ContactPageSettings
        fields = ("title", "intro", "phone", "phone_label")
        labels = {
            "title": "عنوان صفحه",
            "intro": "متن صفحه",
            "phone": "شماره تماس",
            "phone_label": "عنوان شماره تماس",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "تماس با ما"}),
            "intro": forms.Textarea(attrs={
                "rows": 6,
                "placeholder": "متن کوتاه و واضحی که در صفحه تماس با ما نمایش داده می‌شود.",
            }),
            "phone": forms.TextInput(attrs={
                "dir": "ltr",
                "inputmode": "tel",
                "autocomplete": "tel",
                "placeholder": "0912 123 4567",
            }),
            "phone_label": forms.TextInput(attrs={"placeholder": "پشتیبانی و تماس"}),
        }

    def clean_phone(self):
        return (self.cleaned_data.get("phone") or "").strip()
