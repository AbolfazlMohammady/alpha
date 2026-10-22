from django.core.management.base import BaseCommand, CommandError

from apps.shop.models import Product, ProductComment
from apps.users.models import User


TEST_PHONE = "+989000000000"


COMMENTS = [
    ("علی", "محمدی", 5, "جنسش خیلی خوبه و دقیقاً مثل عکس بود. از کیفیت دوختش راضی‌ام."),
    ("سارا", "رضایی", 5, "رنگ محصول خیلی قشنگه و بسته‌بندی هم مرتب و تمیز به دستم رسید."),
    ("مریم", "احمدی", 4, "کیفیت کار خوبه و اندازه‌اش برای استفاده روزمره کاملاً مناسبه."),
    ("نیما", "کریمی", 5, "خیلی سبک و خوش‌دسته. چیزی که بیشتر از همه دوست داشتم کیفیت متریالش بود."),
    ("نگار", "حسینی", 4, "از خرید راضی بودم؛ ظاهر محصول حتی از چیزی که توی عکس دیدم بهتر بود."),
]


class Command(BaseCommand):
    help = "Create sample approved product comments for local/staging testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm that these are demo/test comments.",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Number of products to seed (default: 5).",
        )
        parser.add_argument(
            "--comments-per-product",
            type=int,
            default=3,
            help="Number of comments per product (default: 3).",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError(
                "این دستور کامنت تستی و قابل‌مشاهده ایجاد می‌کند. "
                "برای اجرای آگاهانه از --confirm استفاده کنید."
            )

        product_limit = max(1, options["count"])
        comments_per_product = max(1, min(options["comments_per_product"], len(COMMENTS)))

        products = list(
            Product.objects.filter(
                is_active=True,
                category__is_active=True,
            ).order_by("id")[:product_limit]
        )
        if not products:
            raise CommandError("هیچ محصول فعالی برای ساخت کامنت تستی پیدا نشد.")

        created_count = 0

        for product in products:
            for index in range(comments_per_product):
                first_name, last_name, rating, body = COMMENTS[index]
                phone = f"+9890000000{index + 1:02d}"
                user, created = User.objects.get_or_create(
                    phone=phone,
                    defaults={
                        "first_name": first_name,
                        "last_name": last_name,
                        "role": "customer",
                        "is_active": True,
                    },
                )
                if created:
                    user.set_unusable_password()
                    user.save(update_fields=["password"])

                _, was_created = ProductComment.objects.get_or_create(
                    product=product,
                    user=user,
                    body=body,
                    defaults={
                        "rating": rating,
                        "status": ProductComment.Status.APPROVED,
                        "verified_purchase": True,
                    },
                )
                if was_created:
                    created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{created_count} کامنت تستی برای {len(products)} محصول ایجاد شد."
            )
        )
