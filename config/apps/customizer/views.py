from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.decorators import method_decorator
from django.views import View

from apps.shop.models import Product, ProductImage, ProductVariant

from .models import Artwork, ArtworkAreaPrice, CustomizerPricingSettings, DesignDraft, DesignerView as DesignerViewModel, PrintArea, PrintAreaView, Product3DAsset
from .product_3d import product_images, source_signature
from .services import (
    CUSTOMIZER_BASE_PRICE,
    GARMENT_PRODUCTION_SPEC,
    create_uploaded_artwork,
    save_design_draft,
    save_design_preview_to_temp,
)
from .temp_storage import resolve_customizer_temp_path
from .tasks import prepare_product_3d, process_uploaded_artwork


def absolute_url(request, path):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{settings.SITE_URL}{path}"


def _schema(data):
    return mark_safe(json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))


def _file_url(request, field):
    if not field or not getattr(field, "name", None):
        return None
    try:
        return request.build_absolute_uri(field.url)
    except (ValueError, OSError):
        return None


def _model_url(request, view, generated_asset=None):
    uploaded = _file_url(request, view.model_3d)
    if uploaded:
        return uploaded
    if generated_asset and generated_asset.status == Product3DAsset.Status.READY:
        return _file_url(request, generated_asset.model_3d) or generated_asset.model_url or None
    return view.model_3d_url or None



def _ensure_default_print_area(product):
    """Create the standard persisted print area used by the standalone 3D studio."""
    area = (
        PrintArea.objects
        .filter(product=product, is_active=True)
        .order_by("sort_order", "id")
        .first()
    )
    if area:
        return area
    return PrintArea.objects.create(
        product=product,
        key="front-print",
        side=PrintArea.Side.FRONT,
        name="ناحیه چاپ اصلی",
        max_width_mm=300,
        max_height_mm=400,
        max_layers=5,
        sort_order=0,
        is_active=True,
    )


def _generation_payload(product):
    images = product_images(product)
    signature = source_signature(images) if images else ""
    asset = Product3DAsset.objects.filter(product=product).first()
    if asset and asset.source_signature != signature and asset.status not in {
        Product3DAsset.Status.QUEUED,
        Product3DAsset.Status.REMOVING_BACKGROUND,
        Product3DAsset.Status.GENERATING,
    }:
        asset.status = Product3DAsset.Status.QUEUED
        asset.task_id = ""
        asset.progress = 0
        asset.model_url = ""
        asset.model_3d = None
        asset.preview_image = None
        asset.error_message = ""
        asset.save(update_fields=["status", "task_id", "progress", "model_url", "model_3d", "preview_image", "error_message", "updated_at"])
    return {
        "status": asset.status if asset else "not_started",
        "progress": asset.progress if asset else 0,
        "error": asset.error_message if asset else "",
        "ready": bool(asset and asset.status == Product3DAsset.Status.READY and (asset.model_3d or asset.model_url)),
        "asset_id": asset.id if asset else None,
        "source_count": len(images),
    }


@method_decorator(login_required, name="dispatch")
class DesignerPageView(View):
    template_name = "customizer/designer.html"

    def get(self, request, product_ref):
        try:
            product_uuid = uuid.UUID(str(product_ref))
        except (ValueError, AttributeError, TypeError):
            product_uuid = None

        product_qs = Product.objects.select_related("category").filter(is_active=True, category__is_active=True)
        if product_uuid:
            product = get_object_or_404(product_qs, uuid=product_uuid)
        else:
            # Legacy links containing the product slug remain valid, while all
            # new generated links use the opaque product UUID.
            product = get_object_or_404(product_qs, slug=product_ref)
        raw_views = list(DesignerViewModel.objects.filter(product=product, is_active=True).exclude(background_image="").order_by("sort_order", "id"))
        views = [view for view in raw_views if _file_url(request, view.background_image)]
        areas = list(PrintArea.objects.filter(product=product, is_active=True).order_by("sort_order", "id"))
        if not areas:
            areas = [_ensure_default_print_area(product)]
        area_maps = list(PrintAreaView.objects.filter(area__in=areas, view__in=views, area__is_active=True, view__is_active=True).select_related("area", "view"))
        generation = _generation_payload(product)
        # Re-read after generation state normalization so a freshly completed
        # Celery job is reflected in designer_data/model URLs on this request.
        generated_asset = Product3DAsset.objects.filter(product=product).first()

        view_data = []
        for view in views:
            background = _file_url(request, view.background_image)
            if not background:
                continue
            view_data.append({"id": view.id, "key": view.key, "name": view.name, "angle": view.angle, "background": background, "mask": _file_url(request, view.mask_image), "model": _model_url(request, view, generated_asset), "model_scale": float(view.model_3d_scale or 1), "width": view.canvas_width, "height": view.canvas_height, "areas": []})
        view_lookup = {item["id"]: item for item in view_data}
        for area_map in area_maps:
            target_view = view_lookup.get(area_map.view_id)
            if target_view:
                target_view["areas"].append({"id": area_map.area_id, "key": area_map.area.key, "name": area_map.area.name, "side": area_map.area.side, "geometry": area_map.geometry, "max_layers": area_map.area.max_layers, "max_width_mm": float(area_map.area.max_width_mm), "max_height_mm": float(area_map.area.max_height_mm)})

        # The 3D studio uses its own stable global GLB; product-specific 2D views are optional.
        if not view_data:
            view_data = [{
                "id": 0,
                "key": "front",
                "name": "جلو",
                "angle": 0,
                "background": "",
                "mask": None,
                "model": None,
                "model_scale": 1,
                "width": 1600,
                "height": 1600,
                "areas": [{
                    "id": area.id,
                    "key": area.key,
                    "name": area.name,
                    "side": area.side,
                    "geometry": [
                        {"x": 0.28, "y": 0.22},
                        {"x": 0.72, "y": 0.22},
                        {"x": 0.72, "y": 0.76},
                        {"x": 0.28, "y": 0.76},
                    ],
                    "max_layers": area.max_layers,
                    "max_width_mm": float(area.max_width_mm),
                    "max_height_mm": float(area.max_height_mm),
                } for area in areas],
            }]

        price_area_ids = {area.id for area in areas}
        pricing = CustomizerPricingSettings.get_solo()
        artworks = list(Artwork.objects.filter(is_active=True, source=Artwork.Source.LIBRARY) .only("id", "code", "name", "image", "base_price", "background_removed").prefetch_related(Prefetch("area_prices", queryset=ArtworkAreaPrice.objects.filter(area_id__in=price_area_ids).select_related("area").only("id", "artwork_id", "area_id", "price", "area__id", "area__product_id", "area__is_active"), to_attr="designer_area_prices")).order_by("name"))
        artwork_data = []
        price_data = {}
        for artwork in artworks:
            image = _file_url(request, artwork.image)
            if image:
                artwork_data.append({
                    "id": artwork.id,
                    "code": artwork.code,
                    "name": artwork.name,
                    "image": image,
                    "base_price": artwork.base_price or 100000,
                    "background_removed": bool(artwork.background_removed),
                })
            for price in getattr(artwork, "designer_area_prices", []):
                if price.area.product_id == product.id and price.area.is_active:
                    price_data[f"{artwork.id}:{price.area_id}"] = price.price

        variants = list(ProductVariant.objects.filter(product=product, is_active=True).select_related("product", "color", "size").only("id", "use_product_price", "price", "stock_quantity", "product__base_price", "color__name", "color__hex_code", "size__name").order_by("price", "id"))
        variants.sort(key=lambda item: item.effective_price)
        variant_data = [{"id": v.id, "price": v.effective_price, "stock": v.stock_quantity, "color": v.color.name, "hex": v.color.hex_code, "size": v.size.name} for v in variants]
        primary_image = ProductImage.objects.filter(product=product, image_type=ProductImage.ImageType.PRIMARY).only("image", "alt_text").first()
        product_image = _file_url(request, primary_image.image) if primary_image else None
        first_background = view_data[0]["background"] if view_data else product_image
        designer_ready = bool(view_data and areas)
        context = {
            "product": product,
            "product_image_url": product_image,
            "designer_views": views,
            "designer_ready": designer_ready,
            "designer_has_3d": designer_ready,
            "designer_model_count": sum(1 for item in view_data if item["model"]),
            "designer_generation": generation,
            "designer_data": _schema({"base_price": int(pricing.tshirt_base_price), "garment_spec": GARMENT_PRODUCTION_SPEC, "product_image": product_image, "views": view_data, "artworks": artwork_data, "prices": price_data, "variants": variant_data, "mode": "3d" if designer_ready else "2d", "generation": generation}),
            "canonical_url": absolute_url(request, request.path),
            "og_title": "استودیو طراحی سه‌بعدی | BABAEI",
            "og_description": "محصول را تحلیل کن، مدل سه‌بعدی واقعی بساز و طرح خودت را روی سطح آن قرار بده.",
            "og_image_url": first_background,
            "designer_schema": _schema({"@context": "https://schema.org", "@type": "WebPage", "name": "استودیو طراحی سه‌بعدی", "url": absolute_url(request, request.path), "isPartOf": {"@type": "WebSite", "name": "BABAEI", "url": settings.SITE_URL}, "inLanguage": "fa-IR"}),
        }
        return render(request, self.template_name, context)


class PrepareProduct3DView(View):
    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
        manual_views = list(product.designer_views.filter(is_active=True).order_by("sort_order", "id"))
        manual_url = next((_model_url(request, view) for view in manual_views if _model_url(request, view)), None)
        if manual_url:
            return JsonResponse({"ok": True, "status": "ready", "source": "manual", "progress": 100, "model_url": manual_url})

        images = product_images(product)
        if not images:
            return JsonResponse({"ok": False, "error": "این محصول تصویر قابل تحلیل ندارد."}, status=422)

        signature = source_signature(images)
        with transaction.atomic():
            asset, _ = Product3DAsset.objects.get_or_create(
                product=product,
                defaults={"source_signature": signature},
            )
            asset = Product3DAsset.objects.select_for_update().get(pk=asset.pk)

            if (
                asset.status == Product3DAsset.Status.READY
                and asset.source_signature == signature
                and (asset.model_3d or asset.model_url)
            ):
                return JsonResponse({
                    "ok": True,
                    "status": "ready",
                    "source": "generated",
                    "progress": 100,
                    "model_url": _file_url(request, asset.model_3d) or asset.model_url or None,
                })

            active_statuses = {
                Product3DAsset.Status.QUEUED,
                Product3DAsset.Status.REMOVING_BACKGROUND,
                Product3DAsset.Status.GENERATING,
            }
            if asset.status in active_statuses:
                # Recover a job only when a worker has clearly disappeared.
                stale_queued = (
                    asset.status == Product3DAsset.Status.QUEUED
                    and asset.updated_at < timezone.now() - timedelta(minutes=10)
                )
                if not stale_queued:
                    return JsonResponse({
                        "ok": True,
                        "status": asset.status,
                        "progress": asset.progress,
                    })

            asset.status = Product3DAsset.Status.QUEUED
            asset.source_signature = signature
            asset.task_id = ""
            asset.progress = 0
            asset.error_message = ""
            asset.model_url = ""
            asset.save(update_fields=[
                "status",
                "source_signature",
                "task_id",
                "progress",
                "error_message",
                "model_url",
                "updated_at",
            ])
            transaction.on_commit(
                lambda asset_id=asset.id: prepare_product_3d.apply_async(args=[asset_id])
            )
        return JsonResponse({
            "ok": True,
            "status": Product3DAsset.Status.QUEUED,
            "progress": 0,
        }, status=202)


class Product3DStatusView(View):
    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
        asset = Product3DAsset.objects.filter(product=product).first()
        if not asset:
            manual_views = list(
                product.designer_views.filter(is_active=True).order_by("sort_order", "id")
            )
            manual_url = next(
                (_model_url(request, view) for view in manual_views if _model_url(request, view)),
                None,
            )
            if manual_url:
                return JsonResponse({
                    "ok": True,
                    "status": "ready",
                    "source": "manual",
                    "progress": 100,
                    "ready": True,
                    "model_url": manual_url,
                    "preview_url": None,
                })
            return JsonResponse({"ok": True, "status": "not_started", "progress": 0})

        # Status requests are intentionally read-only. Meshy is polled by
        # Celery so a busy browser cannot turn every status check into an
        # outbound provider request.
        return JsonResponse({
            "ok": True,
            "status": asset.status,
            "progress": asset.progress,
            "error": asset.error_message,
            "ready": (
                asset.status == Product3DAsset.Status.READY
                and bool(asset.model_3d or asset.model_url)
            ),
            "model_url": _file_url(request, asset.model_3d) or asset.model_url or None,
            "preview_url": _file_url(request, asset.preview_image),
        })


class SaveDesignView(View):
    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
        try:
            if request.content_type.startswith("multipart/form-data"):
                payload = json.loads(request.POST.get("payload", "{}"))
                preview_front = request.FILES.get("preview_front")
                preview_back = request.FILES.get("preview_back")
            else:
                payload = json.loads(request.body.decode("utf-8"))
                preview_front = preview_back = None
            if not isinstance(payload, dict):
                raise ValidationError("اطلاعات طراحی نامعتبر است.")
            variant_id = payload.pop("variant_id", None)
            variant = get_object_or_404(ProductVariant, id=variant_id, product=product, is_active=True) if variant_id else None
            draft = save_design_draft(request=request, product=product, payload=payload, variant=variant)
            raw_layers = payload.get("layers", [])
            if raw_layers and draft.payload.get("layers"):
                for normalized_layer, raw_layer in zip(draft.payload["layers"], raw_layers):
                    if isinstance(raw_layer, dict) and raw_layer.get("three_d"):
                        normalized_layer["three_d"] = raw_layer["three_d"]
                draft.save(update_fields=["payload", "updated_at"])
            update_fields = []
            if preview_front:
                draft.temp_preview_front_path = save_design_preview_to_temp(
                    draft=draft,
                    preview_file=preview_front,
                    side="front",
                )
                update_fields.append("temp_preview_front_path")
            if preview_back:
                draft.temp_preview_back_path = save_design_preview_to_temp(
                    draft=draft,
                    preview_file=preview_back,
                    side="back",
                )
                update_fields.append("temp_preview_back_path")
            if update_fields:
                update_fields.append("updated_at")
                draft.save(update_fields=update_fields)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"ok": False, "error": "اطلاعات طراحی نامعتبر است."}, status=400)
        except ValidationError as exc:
            message = exc.message if hasattr(exc, "message") else str(exc)
            return JsonResponse({"ok": False, "error": message}, status=422)
        return JsonResponse({"ok": True, "draft_id": str(draft.uuid), "design_code": draft.design_code, "total_price": draft.total_price})


class AddDesignToCartView(View):
    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
        try:
            if request.content_type.startswith("multipart/form-data"):
                payload = json.loads(request.POST.get("payload", "{}"))
                preview_front = request.FILES.get("preview_front")
                preview_back = request.FILES.get("preview_back")
            else:
                payload = json.loads(request.body.decode("utf-8"))
                preview_front = preview_back = None
            if not isinstance(payload, dict):
                raise ValidationError("اطلاعات طراحی نامعتبر است.")
            variant_id = payload.pop("variant_id", None)
            variant = get_object_or_404(ProductVariant, id=variant_id, product=product, is_active=True) if variant_id else None
            from apps.orders.services import add_design_to_cart
            with transaction.atomic():
                draft = save_design_draft(request=request, product=product, payload=payload, variant=variant)
                update_fields = []
                if preview_front:
                    draft.temp_preview_front_path = save_design_preview_to_temp(
                        draft=draft,
                        preview_file=preview_front,
                        side="front",
                    )
                    update_fields.append("temp_preview_front_path")
                if preview_back:
                    draft.temp_preview_back_path = save_design_preview_to_temp(
                        draft=draft,
                        preview_file=preview_back,
                        side="back",
                    )
                    update_fields.append("temp_preview_back_path")
                if update_fields:
                    update_fields.append("updated_at")
                    draft.save(update_fields=update_fields)
                add_design_to_cart(request, design=draft, quantity=1)
                draft.status = DesignDraft.Status.CART
                draft.save(update_fields=["status", "updated_at"])
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"ok": False, "error": "اطلاعات طراحی نامعتبر است."}, status=400)
        except ValidationError as exc:
            message = exc.message if hasattr(exc, "message") else str(exc)
            return JsonResponse({"ok": False, "error": message}, status=422)
        except ValueError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        return JsonResponse({
            "ok": True,
            "design_id": str(draft.uuid),
            "design_code": draft.design_code,
            "total_price": draft.total_price,
            "redirect": reverse("orders:cart"),
        })


def _artwork_payload(request, artwork):
    return {
        "id": artwork.id,
        "code": artwork.code,
        "name": artwork.name,
        "image": (
            _file_url(request, artwork.image)
            or (
                request.build_absolute_uri(
                    reverse(
                        "customizer:artwork_temp_image",
                        kwargs={"slug": request.resolver_match.kwargs.get("slug"), "artwork_id": artwork.id},
                    )
                )
                if artwork.source == Artwork.Source.UPLOAD and artwork.temp_image_path
                else None
            )
        ),
        "base_price": artwork.base_price,
        "background_removed": bool(artwork.background_removed),
        "processing_status": artwork.processing_status,
    }


class ArtworkTemporaryImageView(View):
    def get(self, request, slug, artwork_id):
        get_object_or_404(
            Product,
            slug=slug,
            is_active=True,
            category__is_active=True,
        )

        queryset = Artwork.objects.filter(
            id=artwork_id,
            source=Artwork.Source.UPLOAD,
        )
        if request.user.is_authenticated:
            queryset = queryset.filter(owner=request.user)
        else:
            session_key = request.session.session_key
            if not session_key:
                return JsonResponse({"ok": False, "error": "نشست معتبر نیست."}, status=404)
            queryset = queryset.filter(owner__isnull=True, session_key=session_key)

        artwork = get_object_or_404(queryset)
        if artwork.processing_status != Artwork.ProcessingStatus.READY or not artwork.temp_image_path:
            return JsonResponse({"ok": False, "error": "فایل موقت تصویر آماده نیست."}, status=404)

        try:
            path = resolve_customizer_temp_path(artwork.temp_image_path)
        except ValueError:
            return JsonResponse({"ok": False, "error": "مسیر فایل نامعتبر است."}, status=404)

        if not path.is_file():
            return JsonResponse({"ok": False, "error": "فایل موقت تصویر پیدا نشد."}, status=404)

        return FileResponse(
            path.open("rb"),
            content_type="image/png" if path.suffix.lower() == ".png" else None,
        )


class DesignTemporaryPreviewView(View):
    def get(self, request, design_uuid, side):
        if side not in {"front", "back"}:
            return JsonResponse({"ok": False, "error": "سمت پیش‌نمایش نامعتبر است."}, status=404)

        draft = get_object_or_404(
            DesignDraft.objects.select_related("product"),
            uuid=design_uuid,
        )
        if not draft.product.is_active or not draft.product.category.is_active:
            return JsonResponse({"ok": False, "error": "طراحی دیگر قابل مشاهده نیست."}, status=404)

        if request.user.is_authenticated:
            if draft.user_id != request.user.id:
                return JsonResponse({"ok": False, "error": "دسترسی به این طراحی مجاز نیست."}, status=403)
        else:
            session_key = request.session.session_key
            if not session_key or draft.user_id is not None or draft.session_key != session_key:
                return JsonResponse({"ok": False, "error": "دسترسی به این طراحی مجاز نیست."}, status=403)

        relative_path = getattr(draft, f"temp_preview_{side}_path")
        if not relative_path:
            return JsonResponse({"ok": False, "error": "پیش‌نمایش موقت موجود نیست."}, status=404)

        try:
            path = resolve_customizer_temp_path(relative_path)
        except ValueError:
            return JsonResponse({"ok": False, "error": "مسیر فایل نامعتبر است."}, status=404)

        if not path.is_file():
            return JsonResponse({"ok": False, "error": "فایل پیش‌نمایش پیدا نشد."}, status=404)

        return FileResponse(
            path.open("rb"),
            content_type="image/webp" if path.suffix.lower() == ".webp" else None,
        )


class UploadArtworkView(View):
    def post(self, request, slug):
        get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
        uploaded = request.FILES.get("image")
        if not uploaded:
            return JsonResponse({"ok": False, "error": "تصویری انتخاب نشده است."}, status=400)

        remove_background = request.POST.get("remove_background") in {"1", "true", "on", "yes"}
        try:
            artwork = create_uploaded_artwork(
                request=request,
                uploaded_file=uploaded,
                strip_background=remove_background,
            )
        except ValidationError as exc:
            message = exc.message if hasattr(exc, "message") else str(exc)
            return JsonResponse({"ok": False, "error": message}, status=422)

        if artwork.processing_status == Artwork.ProcessingStatus.PROCESSING:
            transaction.on_commit(
                lambda artwork_id=artwork.id: process_uploaded_artwork.apply_async(
                    args=[artwork_id]
                )
            )
            return JsonResponse({
                "ok": True,
                "status": Artwork.ProcessingStatus.PROCESSING,
                "artwork_id": artwork.id,
                "status_url": reverse(
                    "customizer:upload_artwork_status",
                    kwargs={"slug": slug, "artwork_id": artwork.id},
                ),
            }, status=202)

        return JsonResponse({
            "ok": True,
            "status": artwork.processing_status,
            "artwork": _artwork_payload(request, artwork),
        })


class ArtworkUploadStatusView(View):
    def get(self, request, slug, artwork_id):
        get_object_or_404(
            Product,
            slug=slug,
            is_active=True,
            category__is_active=True,
        )

        queryset = Artwork.objects.filter(
            id=artwork_id,
            source=Artwork.Source.UPLOAD,
        )
        if request.user.is_authenticated:
            queryset = queryset.filter(owner=request.user)
        else:
            session_key = request.session.session_key
            if not session_key:
                return JsonResponse({"ok": False, "error": "نشست معتبر نیست."}, status=404)
            queryset = queryset.filter(
                owner__isnull=True,
                session_key=session_key,
            )

        artwork = get_object_or_404(queryset)
        payload = {
            "ok": True,
            "status": artwork.processing_status,
        }
        if artwork.processing_status == Artwork.ProcessingStatus.READY:
            payload["artwork"] = _artwork_payload(request, artwork)
        elif artwork.processing_status == Artwork.ProcessingStatus.FAILED:
            payload["error"] = "پردازش تصویر ناموفق بود؛ لطفاً دوباره تلاش کنید."
        return JsonResponse(payload)
