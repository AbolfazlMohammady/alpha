from __future__ import annotations

import base64
import hashlib
import io
import json
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageFile, UnidentifiedImageError

from .models import Product3DAsset, Product3DSource

MESHY_URL = "https://api.meshy.ai/openapi/v1"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_IMAGES = 4
NORMALIZED_SIZE = 1600


def _json_request(url, *, method="GET", payload=None, headers=None, timeout=90):
    body = None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValidationError(f"سرویس ساخت مدل سه‌بعدی پاسخ {exc.code} داد: {detail[:400]}") from exc
    except (urlerror.URLError, TimeoutError) as exc:
        raise ValidationError("ارتباط با سرویس ساخت مدل سه‌بعدی برقرار نشد.") from exc


def product_images(product):
    return list(product.images.all().only("id", "image", "image_type", "sort_order").order_by("sort_order", "id")[:MAX_SOURCE_IMAGES])


def source_signature(images):
    value = "|".join(f"{item.id}:{item.image.name}" for item in images)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _transparent_png(raw):
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("یکی از تصاویر محصول قابل پردازش نیست.") from exc
    rgba = image.convert("RGBA")
    rgba.thumbnail((NORMALIZED_SIZE, NORMALIZED_SIZE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    rgba.save(output, format="PNG", optimize=True)
    return output.getvalue(), rgba


def _data_uri(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def _remove_bg(raw, filename):
    api_key = getattr(settings, "REMOVE_BG_API_KEY", "").strip()
    if not api_key:
        raise ValidationError("REMOVE_BG_API_KEY تنظیم نشده است؛ برای ساخت مدل باید حذف پس‌زمینه فعال باشد.")
    boundary = "----BabaeiProduct3D"
    content_type = "image/png" if str(filename).lower().endswith(".png") else "image/jpeg"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"size\"\r\n\r\nfull\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"format\"\r\n\r\npng\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\nproduct\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image_file\"; filename=\"product\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
        raw,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urlrequest.Request(
        "https://api.remove.bg/v1.0/removebg",
        data=body,
        headers={"X-Api-Key": api_key, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=90) as response:
            if response.status != 200:
                raise ValidationError("حذف پس‌زمینه تصویر محصول ناموفق بود.")
            return response.read()
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValidationError(f"حذف پس‌زمینه ناموفق بود: {detail[:300]}") from exc
    except (urlerror.URLError, TimeoutError) as exc:
        raise ValidationError("ارتباط با سرویس حذف پس‌زمینه برقرار نشد.") from exc


def _prepare_source(product_image):
    product_image.image.open("rb")
    try:
        raw = product_image.image.read(MAX_SOURCE_BYTES + 1)
    finally:
        product_image.image.close()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValidationError("حجم یکی از تصاویر محصول بیشتر از ۲۰ مگابایت است.")
    _, original = _transparent_png(raw)
    has_alpha = original.getchannel("A").getextrema()[0] < 255
    processed = raw if has_alpha else _remove_bg(raw, product_image.image.name)
    processed, image = _transparent_png(processed)
    bbox = image.getchannel("A").getbbox()
    width, height = image.size
    analysis = {
        "width": width,
        "height": height,
        "aspect_ratio": round(width / max(height, 1), 5),
        "foreground_bbox": {
            "left": round((bbox[0] / width), 5) if bbox else 0,
            "top": round((bbox[1] / height), 5) if bbox else 0,
            "right": round((bbox[2] / width), 5) if bbox else 1,
            "bottom": round((bbox[3] / height), 5) if bbox else 1,
        },
        "background_removed": True,
    }
    return processed, analysis


def _create_meshy_task(image_data_uris):
    api_key = getattr(settings, "MESHY_API_KEY", "").strip()
    if not api_key:
        raise ValidationError("MESHY_API_KEY تنظیم نشده است؛ برای ساخت مدل سه‌بعدی آن را در .env قرار بدهید.")
    multi = len(image_data_uris) > 1
    endpoint = f"{MESHY_URL}/multi-image-to-3d" if multi else f"{MESHY_URL}/image-to-3d"
    payload = {
        "image_urls": image_data_uris,
        "ai_model": getattr(settings, "MESHY_MODEL", "latest"),
        "should_texture": True,
        "enable_pbr": False,
        "texture_resolution": "2k",
        "target_formats": ["glb"],
        "auto_size": True,
        "origin_at": "bottom",
        "multi_view_thumbnails": True,
    } if multi else {
        "image_url": image_data_uris[0],
        "ai_model": getattr(settings, "MESHY_MODEL", "latest"),
        "should_texture": True,
        "enable_pbr": False,
        "texture_resolution": "2k",
        "target_formats": ["glb"],
        "auto_size": True,
        "origin_at": "bottom",
        "alpha_thumbnail": True,
    }
    _, response = _json_request(endpoint, method="POST", payload=payload, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
    task_id = response.get("result")
    if not task_id:
        raise ValidationError("سرویس ساخت مدل شناسه وظیفه برنگرداند.")
    return task_id


def get_meshy_task(asset):
    api_key = getattr(settings, "MESHY_API_KEY", "").strip()
    if not api_key:
        raise ValidationError("MESHY_API_KEY تنظیم نشده است.")
    source_count = int((asset.analysis or {}).get("source_count", 1))
    endpoint_name = "multi-image-to-3d" if source_count > 1 else "image-to-3d"
    _, response = _json_request(
        f"{MESHY_URL}/{endpoint_name}/{asset.task_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    return response


def download_binary(url):
    req = urlrequest.Request(url, headers={"User-Agent": "BabaeiProduct3D/1.0"})
    try:
        with urlrequest.urlopen(req, timeout=120) as response:
            return response.read()
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError) as exc:
        raise ValidationError("دریافت فایل مدل سه‌بعدی ناموفق بود.") from exc


def prepare_product_asset(asset: Product3DAsset):
    images = product_images(asset.product)
    if not images:
        raise ValidationError("این محصول حداقل یک تصویر برای ساخت مدل سه‌بعدی نیاز دارد.")
    asset.status = Product3DAsset.Status.REMOVING_BACKGROUND
    asset.progress = 10
    asset.error_message = ""
    asset.save(update_fields=["status", "progress", "error_message", "updated_at"])
    asset.source_signature = source_signature(images)
    asset.sources.all().delete()
    uris = []
    analysis = {"source_count": len(images), "sources": []}
    for index, product_image in enumerate(images):
        processed, image_analysis = _prepare_source(product_image)
        source = Product3DSource.objects.create(asset=asset, product_image=product_image, sort_order=index, background_removed=True)
        source.processed_image.save(f"source-{product_image.id}.png", ContentFile(processed), save=True)
        uris.append(_data_uri(processed))
        analysis["sources"].append({"product_image_id": product_image.id, **image_analysis})
        asset.progress = min(45, 10 + ((index + 1) * 35 // len(images)))
        asset.save(update_fields=["progress", "updated_at"])
    asset.analysis = analysis
    asset.status = Product3DAsset.Status.GENERATING
    asset.progress = 50
    asset.save(update_fields=["analysis", "status", "progress", "source_signature", "updated_at"])
    asset.task_id = _create_meshy_task(uris)
    asset.save(update_fields=["task_id", "updated_at"])
    return asset


def refresh_product_asset(asset: Product3DAsset):
    response = get_meshy_task(asset)
    status = str(response.get("status", "")).upper()
    asset.progress = min(95, max(asset.progress, int(response.get("progress") or asset.progress)))
    if status in {"PENDING", "IN_PROGRESS", "PROCESSING"}:
        asset.status = Product3DAsset.Status.GENERATING
        asset.save(update_fields=["status", "progress", "updated_at"])
        return asset
    if status != "SUCCEEDED":
        error_message = ((response.get("task_error") or {}).get("message") or "ساخت مدل سه‌بعدی ناموفق بود.")
        asset.status = Product3DAsset.Status.FAILED
        asset.error_message = error_message[:2000]
        asset.save(update_fields=["status", "error_message", "updated_at"])
        return asset
    model_url = (response.get("model_urls") or {}).get("glb")
    preview_url = response.get("thumbnail_url") or response.get("alpha_thumbnail_url")
    if not model_url:
        asset.status = Product3DAsset.Status.FAILED
        asset.error_message = "مدل GLB از سرویس دریافت نشد."
        asset.save(update_fields=["status", "error_message", "updated_at"])
        return asset
    asset.model_3d.save("product.glb", ContentFile(download_binary(model_url)), save=False)
    asset.model_url = model_url
    if preview_url:
        try:
            asset.preview_image.save("preview.png", ContentFile(download_binary(preview_url)), save=False)
        except ValidationError:
            pass
    asset.status = Product3DAsset.Status.READY
    asset.progress = 100
    asset.error_message = ""
    asset.save()
    return asset
