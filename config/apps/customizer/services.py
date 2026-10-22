from __future__ import annotations

import math
import uuid
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from .models import Artwork, ArtworkAreaPrice, CustomizerPricingSettings, DesignDraft, DesignLayer, PrintAreaView
from .temp_storage import delete_customizer_temp_file, resolve_customizer_temp_path, save_bytes_to_temp, save_uploaded_file_to_temp

EPSILON = 1e-7
CUSTOM_UPLOAD_PRICE = 100000
CUSTOMIZER_BASE_PRICE = 1000000
GARMENT_PRODUCTION_SPEC = {
    "unit": "cm",
    "body": {"width": 47, "height": 68},
    "shoulder_width": 36,
    "collar": {"width": 14, "depth": 9},
    "sleeves": {
        "top_length": 21,
        "edge_length": 16,
        "armhole_curve": 23,
        "outer_width": 10,
    },
    "body_side_length": 46,
    "print_surface": "body_only",
}


def save_design_preview_to_temp(*, draft, preview_file, side: str) -> str:
    if side not in {"front", "back"}:
        raise ValueError("سمت پیش‌نمایش نامعتبر است.")

    return save_uploaded_file_to_temp(
        preview_file,
        directory=f"designs/{draft.uuid}/previews",
        filename=f"{draft.design_code}-{side}{Path(preview_file.name).suffix or '.webp'}",
    )


def promote_uploaded_artwork(artwork: Artwork) -> None:
    if artwork.source != Artwork.Source.UPLOAD:
        return

    if artwork.image and artwork.image.name:
        if artwork.temp_image_path:
            delete_customizer_temp_file(artwork.temp_image_path)
            artwork.temp_image_path = ""
            artwork.save(update_fields=["temp_image_path", "updated_at"])
        return

    if not artwork.temp_image_path:
        raise ValidationError("فایل موقت لیبل پیدا نشد؛ امکان نهایی‌سازی طراحی وجود ندارد.")

    temp_path = resolve_customizer_temp_path(artwork.temp_image_path)
    if not temp_path.is_file():
        raise ValidationError("فایل موقت لیبل دیگر وجود ندارد.")

    old_temp_path = artwork.temp_image_path
    artwork.image.save(
        f"{artwork.uuid}.png",
        ContentFile(temp_path.read_bytes()),
        save=False,
    )
    artwork.temp_image_path = ""
    artwork.save(update_fields=["image", "temp_image_path", "updated_at"])
    delete_customizer_temp_file(old_temp_path)


def _promote_design_preview(draft: DesignDraft, side: str) -> None:
    temp_field = f"temp_preview_{side}_path"
    media_field = f"preview_{side}"
    temp_path_value = getattr(draft, temp_field)

    if not temp_path_value:
        return

    temp_path = resolve_customizer_temp_path(temp_path_value)
    if not temp_path.is_file():
        raise ValidationError(f"پیش‌نمایش موقت {side} طراحی پیدا نشد.")

    getattr(draft, media_field).save(
        f"{draft.design_code}-{side}.webp",
        ContentFile(temp_path.read_bytes()),
        save=False,
    )
    old_temp_path = temp_path_value
    setattr(draft, temp_field, "")
    delete_customizer_temp_file(old_temp_path)


def promote_design_assets_for_order(order) -> None:
    design_ids = list(
        order.items
        .exclude(custom_design_id=None)
        .values_list("custom_design_id", flat=True)
        .distinct()
    )
    if not design_ids:
        return

    designs = (
        DesignDraft.objects
        .filter(id__in=design_ids)
        .prefetch_related("layers__artwork")
    )

    for draft in designs:
        artworks = {
            layer.artwork
            for layer in draft.layers.all()
            if layer.artwork_id and layer.artwork.source == Artwork.Source.UPLOAD
        }
        for artwork in artworks:
            promote_uploaded_artwork(artwork)

        front_or_back_promoted = False
        for side in ("front", "back"):
            before = bool(getattr(draft, f"temp_preview_{side}_path"))
            if before:
                _promote_design_preview(draft, side)
                front_or_back_promoted = True

        if front_or_back_promoted:
            draft.save(
                update_fields=[
                    "preview_front",
                    "preview_back",
                    "temp_preview_front_path",
                    "temp_preview_back_path",
                    "updated_at",
                ]
            )


def _is_3d_forbidden_area(area):
    value = f"{area.key or ''} {area.name or ''}".lower()
    return any(token in value for token in ("sleeve", "آستین", "collar", "یقه", "inside", "داخل"))


@dataclass(frozen=True)
class Placement:
    """Placement normalized to the print-area bounding box."""
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0


def _points(geometry):
    return [(float(p["x"]), float(p["y"])) for p in geometry]


def _cross(a, b, c):
    return (b[1] - a[1]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[1] - a[1])


def _on_segment(a, b, c):
    return (
        min(a[0], c[0]) - EPSILON <= b[0] <= max(a[0], c[0]) + EPSILON
        and min(a[1], c[1]) - EPSILON <= b[1] <= max(a[1], c[1]) + EPSILON
        and abs(_cross(a, b, c)) <= EPSILON
    )


def point_in_polygon(point, polygon):
    if any(_on_segment(polygon[i - 1], point, polygon[i]) for i in range(len(polygon))):
        return True
    x, y = point
    inside = False
    for i, current in enumerate(polygon):
        previous = polygon[i - 1]
        if (previous[1] > y) != (current[1] > y):
            x_intersection = (current[0] - previous[0]) * (y - previous[1]) / (current[1] - previous[1]) + previous[0]
            if x < x_intersection:
                inside = not inside
    return inside


def _proper_segment_intersection(a, b, c, d):
    c1, c2 = _cross(a, b, c), _cross(a, b, d)
    c3, c4 = _cross(c, d, a), _cross(c, d, b)
    return ((c1 > EPSILON and c2 < -EPSILON) or (c1 < -EPSILON and c2 > EPSILON)) and ((c3 > EPSILON and c4 < -EPSILON) or (c3 < -EPSILON and c4 > EPSILON))


def rotated_rect_corners(placement: Placement):
    half_width, half_height = placement.width / 2, placement.height / 2
    radians = math.radians(placement.rotation)
    cos_value, sin_value = math.cos(radians), math.sin(radians)
    return [
        (
            placement.x + local_x * cos_value - local_y * sin_value,
            placement.y + local_x * sin_value + local_y * cos_value,
        )
        for local_x, local_y in ((-half_width, -half_height), (half_width, -half_height), (half_width, half_height), (-half_width, half_height))
    ]


def rect_inside_polygon(placement: Placement, polygon):
    corners = rotated_rect_corners(placement)
    if not all(point_in_polygon(corner, polygon) for corner in corners):
        return False
    for i, start in enumerate(corners):
        end = corners[(i + 1) % 4]
        for j, boundary_start in enumerate(polygon):
            boundary_end = polygon[(j + 1) % len(polygon)]
            if _proper_segment_intersection(start, end, boundary_start, boundary_end):
                return False
    return True


def oriented_rects_overlap(first: Placement, second: Placement):
    first_points = rotated_rect_corners(first)
    second_points = rotated_rect_corners(second)
    axes = []
    for points in (first_points, second_points):
        for i in range(2):
            edge = (points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
            length = math.hypot(*edge) or 1.0
            axes.append((-edge[1] / length, edge[0] / length))
    for axis in axes:
        first_projection = [p[0] * axis[0] + p[1] * axis[1] for p in first_points]
        second_projection = [p[0] * axis[0] + p[1] * axis[1] for p in second_points]
        if max(first_projection) <= min(second_projection) + EPSILON or max(second_projection) <= min(first_projection) + EPSILON:
            return False
    return True


def _area_bounds(geometry):
    points = _points(geometry)
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _to_canvas_placement(placement: Placement, geometry):
    min_x, min_y, width, height = _area_bounds(geometry)
    return Placement(
        x=min_x + placement.x * width,
        y=min_y + placement.y * height,
        width=placement.width * width,
        height=placement.height * height,
        rotation=placement.rotation,
    )


def validate_placement(area, view_map, placement, existing):
    if not (0.0 <= placement.x <= 1.0 and 0.0 <= placement.y <= 1.0):
        raise ValidationError("لیبل باید داخل محدوده چاپ قرار بگیرد.")
    if not (0.01 <= placement.width <= 1.0 and 0.01 <= placement.height <= 1.0):
        raise ValidationError("ابعاد لیبل نامعتبر است.")
    if not -180.0 <= placement.rotation <= 180.0:
        raise ValidationError("زاویه لیبل نامعتبر است.")

    geometry = _points(view_map.geometry)
    canvas_placement = _to_canvas_placement(placement, view_map.geometry)
    if not rect_inside_polygon(canvas_placement, geometry):
        raise ValidationError(f"لیبل «{area.name}» نباید از محدوده چاپ خارج شود.")
    if any(oriented_rects_overlap(canvas_placement, other) for other in existing):
        raise ValidationError(f"لیبل‌های ناحیه «{area.name}» نباید روی هم قرار بگیرند.")


def _accessible_artwork_queryset(*, artwork_ids, request):
    queryset = Artwork.objects.filter(
        id__in=artwork_ids,
        is_active=True,
        processing_status=Artwork.ProcessingStatus.READY,
    )
    if request is None:
        return queryset.filter(source=Artwork.Source.LIBRARY)
    public = queryset.filter(source=Artwork.Source.LIBRARY)
    if request.user.is_authenticated:
        private = queryset.filter(source=Artwork.Source.UPLOAD, owner=request.user)
    else:
        private = queryset.filter(source=Artwork.Source.UPLOAD, session_key=request.session.session_key)
    return public | private


def validate_body_placement(placement: Placement, existing):
    """Validate a 3D label against the shirt body coordinate space.

    The 3D editor uses the whole front/back torso as its simple 2D canvas.
    PrintArea geometry is intentionally not used here; the UI already limits
    placement to the actual shirt body surface.
    """
    if not (0.0 <= placement.x <= 1.0 and 0.0 <= placement.y <= 1.0):
        raise ValidationError("لیبل باید داخل بدنه تیشرت قرار بگیرد.")
    if not (0.01 <= placement.width <= 1.0 and 0.01 <= placement.height <= 1.0):
        raise ValidationError("ابعاد لیبل نامعتبر است.")
    if not -180.0 <= placement.rotation <= 180.0:
        raise ValidationError("زاویه لیبل نامعتبر است.")
    # In 3D garment-body mode, labels do not reserve invisible collision
    # rectangles. Adjacent artwork is allowed; the artwork itself defines what
    # the customer sees on the shirt.


def validate_design_payload(product, payload, variant=None, request=None):
    if not isinstance(payload, dict):
        raise ValidationError("اطلاعات طراحی نامعتبر است.")

    raw_layers = payload.get("layers", [])
    if not isinstance(raw_layers, list) or len(raw_layers) > 30:
        raise ValidationError("تعداد یا ساختار لایه‌های طراحی نامعتبر است.")

    if variant is not None and (
        variant.product_id != product.id
        or not variant.is_active
        or variant.stock_quantity <= 0
    ):
        raise ValidationError("رنگ و سایز انتخاب‌شده موجود نیست.")
    if variant is None and product.variants.filter(is_active=True).exists():
        raise ValidationError("لطفاً رنگ و سایز لباس را انتخاب کنید.")

    areas = {area.id: area for area in product.print_areas.filter(is_active=True)}
    views = {view.id: view for view in product.designer_views.filter(is_active=True)}
    maps = {
        (item.area_id, item.view_id): item
        for item in PrintAreaView.objects.filter(
            area__product=product,
            area__is_active=True,
            view__is_active=True,
        ).select_related("area", "view")
    }

    artwork_ids = []
    for raw in raw_layers:
        if not isinstance(raw, dict):
            raise ValidationError("ساختار یکی از لایه‌ها نامعتبر است.")
        if str(raw.get("type", "artwork")) == "text":
            continue
        try:
            artwork_ids.append(int(raw["artwork_id"]))
        except (KeyError, TypeError, ValueError):
            raise ValidationError("یکی از لیبل‌های انتخاب‌شده معتبر نیست.")

    artworks = {
        a.id: a
        for a in _accessible_artwork_queryset(
            artwork_ids=artwork_ids,
            request=request,
        )
    }
    prices = {
        (row.artwork_id, row.area_id): row.price
        for row in ArtworkAreaPrice.objects.filter(
            artwork_id__in=artworks,
            area_id__in=areas,
        )
    }

    parsed = []
    for raw in raw_layers:
        layer_type = str(raw.get("type", "artwork")).lower()
        if layer_type not in {"artwork", "text"}:
            raise ValidationError("نوع لایه طراحی نامعتبر است.")

        try:
            area = areas[int(raw["area_id"])]
            side = str(raw.get("side", "front")).lower()
            if side not in {"front", "back"}:
                raise ValidationError("سمت لباس نامعتبر است.")

            placement = Placement(
                x=float(raw["x"]),
                y=float(raw["y"]),
                width=float(raw["width"]),
                height=float(raw["height"]),
                rotation=float(raw.get("rotation", 0)),
            )
        except (KeyError, TypeError, ValueError):
            raise ValidationError("یکی از ناحیه‌ها یا مختصات طراحی معتبر نیست.")

        if _is_3d_forbidden_area(area):
            raise ValidationError(f"ناحیه «{area.name}» برای چاپ روی لباس مجاز نیست.")
        if not math.isfinite(
            placement.x + placement.y + placement.width + placement.height + placement.rotation
        ):
            raise ValidationError("مختصات لایه نامعتبر است.")

        artwork = None
        text = ""
        text_style = {}

        if layer_type == "artwork":
            try:
                artwork = artworks[int(raw["artwork_id"])]
            except (KeyError, TypeError, ValueError):
                raise ValidationError("یکی از لیبل‌های انتخاب‌شده معتبر نیست.")
            if not artwork.is_active:
                raise ValidationError("این لیبل دیگر فعال نیست.")
        else:
            text = str(raw.get("text", "")).strip()[:120]
            if not text:
                raise ValidationError("متن طراحی نمی‌تواند خالی باشد.")
            raw_style = raw.get("text_style", {})
            text_style = raw_style if isinstance(raw_style, dict) else {}

        parsed.append({
            "area": area,
            "artwork": artwork,
            "side": side,
            "layer_type": layer_type,
            "text": text,
            "text_style": text_style,
            "placement": placement,
        })

    counts = {}
    for item in parsed:
        key = (item["side"], item["area"].id)
        counts[key] = counts.get(key, 0) + 1
    for (side, area_id), count in counts.items():
        if count > areas[area_id].max_layers:
            raise ValidationError(
                f"تعداد لایه‌های سمت «{side}» در ناحیه «{areas[area_id].name}» بیش از حد مجاز است."
            )

    coordinate_space = str(payload.get("coordinate_space", "")).strip().lower()

    for side in ("front", "back"):
        for area_id, area in areas.items():
            area_layers = [
                item for item in parsed
                if item["side"] == side and item["area"].id == area_id
            ]
            if not area_layers:
                continue

            if coordinate_space == "garment_body":
                # The 3D studio treats the shirt body itself as the 2D canvas.
                # Front and back are separate surfaces, so labels on opposite
                # sides never collide.
                existing = []
                for item in area_layers:
                    validate_body_placement(item["placement"], existing)
                    existing.append(item["placement"])
                continue

            # Legacy 2D/customizer payloads still use configured PrintAreaView
            # geometry exactly as before.
            side_views = [
                view for view in views.values()
                if str(view.key or "").strip().lower() == side
            ] or list(views.values())

            for view in side_views:
                view_map = maps.get((area_id, view.id))
                if not view_map:
                    continue
                existing = []
                for item in area_layers:
                    validate_placement(area, view_map, item["placement"], existing)
                    existing.append(
                        _to_canvas_placement(item["placement"], view_map.geometry)
                    )

    garment_type = str(payload.get("garment_type", "tshirt")).strip().lower()
    if garment_type not in {"tshirt"}:
        raise ValidationError("نوع لباس انتخاب‌شده معتبر نیست.")

    garment_model = str(payload.get("garment_model", "")).strip()[:160]

    pricing = CustomizerPricingSettings.get_solo()
    base_price = int(pricing.tshirt_base_price)
    total = base_price

    normalized_layers = []
    for item in parsed:
        artwork = item["artwork"]
        if artwork is None:
            price = 0
        elif artwork.source == Artwork.Source.UPLOAD:
            price = int(pricing.customer_label_price)
        else:
            price = prices.get(
                (artwork.id, item["area"].id),
                artwork.base_price or CUSTOM_UPLOAD_PRICE,
            )
        total += int(price)
        normalized_layers.append({
            "type": item["layer_type"],
            "artwork_id": artwork.id if artwork is not None else None,
            "artwork_code": artwork.code if artwork is not None else None,
            "artwork_name": artwork.name if artwork is not None else None,
            "price": int(price),
            "area_id": item["area"].id,
            "area_key": item["area"].key,
            "area_name": item["area"].name,
            "side": item["side"],
            "x": round(item["placement"].x, 6),
            "y": round(item["placement"].y, 6),
            "width": round(item["placement"].width, 6),
            "height": round(item["placement"].height, 6),
            "rotation": round(item["placement"].rotation, 4),
            "text": item["text"],
            "text_style": item["text_style"],
        })

    coordinate_space = "garment_body" if str(payload.get("coordinate_space", "")).strip().lower() == "garment_body" else "print_area_bbox"
    normalized = {
        "version": 2,
        "coordinate_space": coordinate_space,
        "garment_spec": GARMENT_PRODUCTION_SPEC,
        "garment_type": garment_type,
        "garment_model": garment_model,
        "base_price": base_price,
        "shirt_spec": {"unit": "cm", "body_width": 47, "body_height": 68, "shoulder_width": 36, "collar_width": 14, "collar_depth": 9, "sleeve_length": 21, "sleeve_width": 16, "sleeve_drop": 23, "underarm_width": 10, "print_zone": "torso_only", "front_and_back": True},
        "layers": normalized_layers,
    }
    return normalized, total, base_price


@transaction.atomic
def save_design_draft(*, request, product, payload, variant=None):
    if not request.session.session_key:
        request.session.create()
    normalized, total_price, base_price = validate_design_payload(
        product, payload, variant=variant, request=request
    )
    draft = DesignDraft.objects.create(
        product=product,
        variant=variant,
        user=request.user if request.user.is_authenticated else None,
        session_key=request.session.session_key,
        status=DesignDraft.Status.DRAFT,
        base_price=base_price,
        total_price=total_price,
        shirt_color=str(payload.get("shirt_color") or "").strip()[:40],
        payload=normalized,
    )
    DesignLayer.objects.bulk_create([
        DesignLayer(
            draft=draft,
            layer_type=(
                DesignLayer.LayerType.TEXT
                if layer["type"] == "text"
                else DesignLayer.LayerType.ARTWORK
            ),
            artwork_id=layer["artwork_id"],
            area_id=layer["area_id"],
            side=layer["side"],
            text=layer["text"],
            text_style=layer["text_style"],
            x=layer["x"],
            y=layer["y"],
            width=layer["width"],
            height=layer["height"],
            rotation=layer["rotation"],
            z_index=index,
        )
        for index, layer in enumerate(normalized["layers"])
    ])
    return draft


@lru_cache(maxsize=1)
def _background_removal_session():
    try:
        from rembg import new_session
    except ImportError as exc:
        raise ValidationError(
            "کتابخانه حذف پس‌زمینه نصب نشده است. "
            "ابتدا وابستگی‌های پروژه را نصب کن."
        ) from exc

    return new_session("isnet-general-use")


def _has_transparency(raw):
    from io import BytesIO
    from PIL import Image

    try:
        with Image.open(BytesIO(raw)) as image:
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            return alpha_min < 250 and alpha_max > 0
    except Exception:
        return False


def _normalize_transparent_png(raw):
    from io import BytesIO
    from PIL import Image

    try:
        with Image.open(BytesIO(raw)) as image:
            rgba = image.convert("RGBA")
            output = BytesIO()
            rgba.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise ValidationError(
            "خروجی حذف پس‌زمینه تصویر معتبر نیست."
        ) from exc


def remove_background(file_obj):
    file_obj.seek(0)
    content = file_obj.read()
    if not content:
        raise ValidationError("فایل تصویر خالی است.")

    try:
        from rembg import remove

        session = _background_removal_session()

        # Use the standard rembg path first. Alpha matting may require an
        # additional optional dependency and can fail even when the normal
        # background-removal path is fully functional.
        output = remove(
            content,
            session=session,
            force_return_bytes=True,
            alpha_matting=False,
            post_process_mask=True,
        )

        # If the standard mask did not contain transparency, try alpha
        # matting as a fallback. Keep this fallback isolated so an optional
        # matting dependency cannot break the normal upload flow.
        if not _has_transparency(output):
            try:
                output = remove(
                    content,
                    session=session,
                    force_return_bytes=True,
                    alpha_matting=True,
                    alpha_matting_foreground_threshold=240,
                    alpha_matting_background_threshold=12,
                    alpha_matting_erode_size=10,
                )
            except Exception:
                pass

    except ValidationError:
        raise
    except ImportError as exc:
        raise ValidationError(
            "کتابخانه حذف پس‌زمینه نصب نشده است. "
            "ابتدا وابستگی‌های پروژه را نصب کن."
        ) from exc
    except Exception as exc:
        raise ValidationError(
            "حذف خودکار پس‌زمینه با خطا متوقف شد؛ لطفاً دوباره تلاش کنید."
        ) from exc

    if not output or not _has_transparency(output):
        raise ValidationError(
            "نتوانستم پس‌زمینه این تصویر را با اطمینان جدا کنم. "
            "یک تصویر واضح‌تر یا با کنتراست بیشتر انتخاب کن."
        )

    return _normalize_transparent_png(output)


def create_uploaded_artwork(*, request, uploaded_file, strip_background=False):
    max_upload_bytes = int(getattr(settings, "CUSTOMIZER_MAX_UPLOAD_BYTES", 15 * 1024 * 1024))
    if getattr(uploaded_file, "size", 0) > max_upload_bytes:
        raise ValidationError("حجم تصویر انتخاب‌شده بیش از حد مجاز است.")
    if not request.session.session_key:
        request.session.create()

    from PIL import Image, ImageFile, UnidentifiedImageError

    ImageFile.LOAD_TRUNCATED_IMAGES = False
    uploaded_file.seek(0)
    try:
        image = Image.open(uploaded_file)
        image.verify()
        uploaded_file.seek(0)
        image = Image.open(uploaded_file)
        width, height = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("فایل انتخاب‌شده یک تصویر معتبر نیست.")

    if width < 300 or height < 300:
        raise ValidationError("ابعاد تصویر باید حداقل ۳۰۰×۳۰۰ پیکسل باشد.")

    has_alpha = False
    if "A" in image.getbands():
        has_alpha = image.getchannel("A").getextrema()[0] < 255
    elif image.mode == "P" and "transparency" in image.info:
        has_alpha = image.convert("RGBA").getchannel("A").getextrema()[0] < 255

    should_process = strip_background and not has_alpha
    artwork = Artwork(
        name=Path(uploaded_file.name).stem[:160],
        source=Artwork.Source.UPLOAD,
        processing_status=(
            Artwork.ProcessingStatus.PROCESSING
            if should_process
            else Artwork.ProcessingStatus.READY
        ),
        background_removed=has_alpha,
        base_price=int(CustomizerPricingSettings.get_solo().customer_label_price),
        owner=request.user if request.user.is_authenticated else None,
        session_key=request.session.session_key,
    )
    artwork.save()

    try:
        artwork.temp_image_path = save_uploaded_file_to_temp(
            uploaded_file,
            directory=f"artworks/{artwork.uuid}",
            filename=uploaded_file.name,
        )
        artwork.save(update_fields=["temp_image_path", "updated_at"])
    except Exception:
        artwork.delete()
        raise

    return artwork
