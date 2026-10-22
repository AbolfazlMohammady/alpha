import hashlib

from django.core.cache import cache
from django.urls import resolve

from .models import AuditLog


ACTION_LABELS = {
    "dashboard": "مشاهده داشبورد",
    "orders": "مشاهده فهرست سفارش‌ها",
    "order_detail": "مشاهده جزئیات سفارش",
    "order_workflow": "تغییر وضعیت سفارش",
    "order_invoice": "مشاهده فاکتور سفارش",
    "comments": "مشاهده نظرات",
    "comment_moderation": "تغییر وضعیت نظر",
    "users": "مشاهده کاربران",
    "user_create": "ایجاد کاربر",
    "user_edit": "ویرایش کاربر",
    "user_delete": "حذف کاربر",
    "products": "مشاهده محصولات",
    "product_create": "ایجاد محصول",
    "product_edit": "ویرایش محصول",
    "product_delete": "حذف محصول",
    "categories": "مشاهده دسته‌بندی‌ها",
    "category_create": "ایجاد دسته‌بندی",
    "category_edit": "ویرایش دسته‌بندی",
    "category_delete": "حذف دسته‌بندی",
    "catalog": "مشاهده رنگ و سایزها",
    "color_create": "ایجاد رنگ",
    "color_edit": "ویرایش رنگ",
    "color_delete": "حذف رنگ",
    "size_create": "ایجاد سایز",
    "size_edit": "ویرایش سایز",
    "size_delete": "حذف سایز",
    "3d_dashboard": "مشاهده بخش طراحی سه‌بعدی",
    "3d_pricing": "ویرایش قیمت‌گذاری طراحی سه‌بعدی",
    "design_detail": "مشاهده جزئیات طراحی",
    "design_complete": "ثبت تکمیل طراحی",
    "artwork_library": "مشاهده کتابخانه لیبل‌ها",
    "artwork_create": "ایجاد لیبل",
    "artwork_edit": "ویرایش لیبل",
    "artwork_delete": "حذف لیبل",
    "customer_artworks": "مشاهده لیبل‌های مشتریان",
    "design_text_download": "دانلود متن طراحی",
    "design_artwork_download": "دانلود فایل لیبل طراحی",
}


class ControlAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_control = request.path == "/control/" or request.path.startswith("/control/")
        if not is_control:
            return self.get_response(request)

        response = self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return response

        try:
            # Django already resolved the URL before the view runs. Reusing the
            # resolver match avoids parsing the URL pattern a second time.
            match = getattr(request, "resolver_match", None) or resolve(request.path)
            url_name = match.url_name or "unknown"
            action = ACTION_LABELS.get(url_name, url_name.replace("_", " ").strip())
            object_id = match.kwargs.get("pk") or match.kwargs.get("uuid")
            suffix = f" (شناسه {object_id})" if object_id else ""

            if request.method == "GET":
                description = f"{action}{suffix}"

                # GET pages are views, not state-changing actions. Keep the
                # audit trail while collapsing repeated refresh/poll requests
                # from the same actor into one entry for a short window.
                dedupe_raw = (
                    f"{user.pk}|{request.path}|{request.META.get('QUERY_STRING', '')}"
                ).encode("utf-8", "ignore")
                dedupe_key = "babaei:audit:get:" + hashlib.sha256(dedupe_raw).hexdigest()
                if not cache.add(dedupe_key, True, timeout=15):
                    return response
            else:
                description = f"{action}{suffix} با درخواست {request.method}"

            status_code = response.status_code
            if 200 <= status_code < 300:
                result = AuditLog.Result.SUCCESS
            elif 300 <= status_code < 400:
                result = AuditLog.Result.REDIRECT
            elif 400 <= status_code < 500:
                result = AuditLog.Result.CLIENT_ERROR
            else:
                result = AuditLog.Result.SERVER_ERROR

            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")

            AuditLog.objects.create(
                actor=user,
                action=action,
                description=description,
                method=request.method if request.method in AuditLog.Method.values else AuditLog.Method.OTHER,
                path=request.path,
                status_code=status_code,
                result=result,
                ip_address=ip,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
                query_string=request.META.get("QUERY_STRING", "")[:2000],
            )
        except Exception:
            # Audit logging must never break the admin panel itself.
            pass

        return response
