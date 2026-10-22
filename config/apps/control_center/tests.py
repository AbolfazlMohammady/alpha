from django.test import TestCase

from apps.orders.models import Order
from apps.users.models import User


class ReadOnlyOrderPaymentWithWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone="09120000000",
            password="test-password",
            first_name="Test",
            last_name="Customer",
        )
        self.staff = User.objects.create_superuser(
            phone="09120000001",
            password="test-password",
        )
        self.order = Order.objects.create(
            user=self.user,
            status=Order.Status.PENDING,
            payment_status=Order.PaymentStatus.UNPAID,
            shipping_status=Order.ShippingStatus.PENDING,
            shipping_title="Home",
            shipping_recipient="Test Customer",
            shipping_phone="+989120000000",
            shipping_province="Tehran",
            shipping_city="Tehran",
            shipping_postal_code="1234567890",
            shipping_address="Test Address",
            subtotal=1000000,
            discount_amount=0,
            shipping_amount=0,
            total_amount=1000000,
        )

    def test_order_detail_is_get_only_for_basic_data(self):
        self.client.force_login(self.staff)
        response = self.client.get(f"/control/orders/{self.order.pk}/")
        self.assertEqual(response.status_code, 200)

    def test_workflow_endpoint_never_marks_unpaid_order_as_paid(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "preparing"},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_paid_order_can_move_through_shipping_workflow(self):
        self.client.force_login(self.staff)
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=("payment_status", "status", "updated_at"))

        self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "preparing"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PROCESSING)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.PREPARING)

        self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "shipped"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.SHIPPED)
        self.assertTrue(self.order.shipped_at)

        self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "delivered"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.DELIVERED)
        self.assertTrue(self.order.delivered_at)

    def test_order_workflow_cannot_go_backward_or_repeat(self):
        self.client.force_login(self.staff)
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.status = Order.Status.PROCESSING
        self.order.shipping_status = Order.ShippingStatus.PREPARING
        self.order.save(
            update_fields=("payment_status", "status", "shipping_status", "updated_at")
        )

        # A completed stage cannot be selected again or moved to an earlier stage.
        for action in ("preparing",):
            response = self.client.post(
                f"/control/orders/{self.order.pk}/workflow/",
                {"action": action},
            )
            self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.order.status, Order.Status.PROCESSING)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.PREPARING)

        self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "shipped"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.SHIPPED)

        response = self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "shipped"},
        )
        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.SHIPPED)

        self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "delivered"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.DELIVERED)

        response = self.client.post(
            f"/control/orders/{self.order.pk}/workflow/",
            {"action": "delivered"},
        )
        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertEqual(self.order.shipping_status, Order.ShippingStatus.DELIVERED)



class CommentModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            phone="09121111111",
            password="test-password",
        )
        cls.customer = User.objects.create_user(
            phone="09122222222",
            password="test-password",
            first_name="علی",
            last_name="رضایی",
        )

        from apps.shop.models import Category, Product, ProductComment

        cls.ProductComment = ProductComment
        category = Category.objects.create(name="تیشرت", slug="comment-test-tshirt")
        product = Product.objects.create(
            category=category,
            name="تیشرت مشکی",
            slug="comment-test-black-tshirt",
            base_price=500000,
        )
        cls.comment = ProductComment.objects.create(
            product=product,
            user=cls.customer,
            body="کیفیت محصول خیلی خوب بود.",
            rating=5,
            status=ProductComment.Status.PENDING,
            verified_purchase=True,
        )

    def test_comments_page_requires_moderator_role(self):
        response = self.client.get("/control/comments/")
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.customer)
        response = self.client.get("/control/comments/")
        self.assertEqual(response.status_code, 403)

    def test_moderator_can_filter_and_approve_comment(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            "/control/comments/",
            {"status": "pending", "rating": "5", "q": "خیلی خوب"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "کیفیت محصول خیلی خوب بود.")
        self.assertContains(response, "تیشرت مشکی")

        response = self.client.post(
            f"/control/comments/{self.comment.pk}/approve/",
        )
        self.assertRedirects(response, "/control/comments/")
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, self.ProductComment.Status.APPROVED)

    def test_moderator_can_reject_comment(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/control/comments/{self.comment.pk}/reject/",
        )
        self.assertRedirects(response, "/control/comments/")
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, self.ProductComment.Status.REJECTED)


class AuditReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            phone="09123333333",
            password="test-password",
            first_name="مدیر",
            last_name="ارشد",
        )
        cls.staff = User.objects.create_user(
            phone="09124444444",
            password="test-password",
            first_name="کارمند",
            last_name="فروشگاه",
            role="store_manager",
        )

    def test_only_superuser_can_open_reports(self):
        response = self.client.get("/control/reports/")
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff)
        response = self.client.get("/control/reports/")
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.superuser)
        response = self.client.get("/control/reports/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "گزارش فعالیت‌ها")

    def test_control_activity_is_logged_with_exact_request_data(self):
        self.client.force_login(self.staff)
        response = self.client.get("/control/", {"q": "orders"})
        self.assertEqual(response.status_code, 200)

        from apps.control_center.models import AuditLog

        log = AuditLog.objects.filter(actor=self.staff, path="/control/").latest("created_at")
        self.assertEqual(log.method, AuditLog.Method.GET)
        self.assertEqual(log.action, "مشاهده داشبورد")
        self.assertEqual(log.status_code, 200)
        self.assertEqual(log.query_string, "q=orders")
        self.assertEqual(log.result, AuditLog.Result.SUCCESS)

    def test_post_activity_is_logged_as_post(self):
        self.client.force_login(self.superuser)
        self.client.post("/control/comments/999999/approve/")

        from apps.control_center.models import AuditLog

        log = AuditLog.objects.filter(
            actor=self.superuser,
            path="/control/comments/999999/approve/",
        ).latest("created_at")
        self.assertEqual(log.method, AuditLog.Method.POST)
        self.assertEqual(log.action, "تغییر وضعیت نظر")
        self.assertEqual(log.status_code, 404)
        self.assertEqual(log.result, AuditLog.Result.CLIENT_ERROR)


class DashboardEmptyStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            phone="09125555555",
            password="test-password",
        )

    def test_dashboard_renders_without_paid_top_products(self):
        self.client.force_login(self.admin)
        response = self.client.get("/control/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["top_products"], [])
