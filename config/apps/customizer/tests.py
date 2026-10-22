import base64
import json

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from apps.shop.models import Category, Product, ProductColor, ProductSize, ProductVariant

from .models import Artwork, ArtworkAreaPrice, CustomizerPricingSettings, DesignDraft, DesignerView, PrintArea, PrintAreaView
from .services import Placement, oriented_rects_overlap, point_in_polygon, validate_design_payload

def make_valid_png(size=(300, 300)):
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", size, (220, 40, 40, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


@pytest.fixture
def product(db):
    category = Category.objects.create(name="تی‌شرت", slug="tshirt")
    return Product.objects.create(category=category, name="تی‌شرت مشکی", slug="black-tshirt", base_price=500000)


@pytest.fixture
def configured_designer(product):
    view = DesignerView.objects.create(
        product=product,
        key="front",
        name="روبه‌رو",
        background_image=SimpleUploadedFile("shirt.png", PNG_1X1, content_type="image/png"),
        canvas_width=1000,
        canvas_height=1000,
    )
    area = PrintArea.objects.create(product=product, key="left-chest", name="سینه چپ", max_layers=2)
    PrintAreaView.objects.create(
        area=area,
        view=view,
        geometry=[
            {"x": 0.30, "y": 0.25},
            {"x": 0.55, "y": 0.25},
            {"x": 0.55, "y": 0.50},
            {"x": 0.30, "y": 0.50},
        ],
    )
    artwork = Artwork.objects.create(
        name="اژدها",
        slug="dragon",
        image=SimpleUploadedFile("dragon.png", PNG_1X1, content_type="image/png"),
        base_price=100000,
    )
    ArtworkAreaPrice.objects.create(artwork=artwork, area=area, price=120000)
    return view, area, artwork


def test_geometry_and_rotated_collision():
    polygon = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert point_in_polygon((.5, .5), polygon)
    assert point_in_polygon((0, .5), polygon)
    assert not point_in_polygon((1.5, .5), polygon)
    assert oriented_rects_overlap(Placement(.5, .5, .2, .2), Placement(.6, .5, .2, .2))
    assert not oriented_rects_overlap(Placement(.2, .2, .1, .1), Placement(.8, .8, .1, .1))


def test_design_payload_calculates_area_specific_price(product, configured_designer):
    _, area, artwork = configured_designer
    payload = {"version": 1, "layers": [{"artwork_id": artwork.id, "area_id": area.id, "x": .5, "y": .5, "width": .3, "height": .3, "rotation": 0}]}
    pricing = CustomizerPricingSettings.get_solo()
    pricing.tshirt_base_price = 500000
    pricing.customer_label_price = 100000
    pricing.save()

    normalized, total = validate_design_payload(product, payload)
    assert normalized["coordinate_space"] == "print_area_bbox"
    assert total == 620000


def test_customer_uploaded_artwork_uses_panel_price(product, configured_designer):
    _, area, _ = configured_designer
    pricing = CustomizerPricingSettings.get_solo()
    pricing.tshirt_base_price = 750000
    pricing.customer_label_price = 180000
    pricing.save()

    uploaded = Artwork.objects.create(
        name="آپلود مشتری",
        slug="customer-upload",
        source=Artwork.Source.UPLOAD,
        image=SimpleUploadedFile("customer.png", PNG_1X1, content_type="image/png"),
        base_price=100000,
    )
    payload = {
        "version": 1,
        "layers": [{
            "artwork_id": uploaded.id,
            "area_id": area.id,
            "x": .5,
            "y": .5,
            "width": .3,
            "height": .3,
            "rotation": 0,
        }],
    }
    normalized, total = validate_design_payload(product, payload)
    assert normalized["base_price"] == 750000
    assert normalized["layers"][0]["price"] == 180000
    assert total == 930000


def test_pricing_page_is_editable(client, django_user_model):
    user = django_user_model.objects.create_user(
        phone="+989121234567",
        password="test-pass-123",
        role="admin",
        is_active=True,
    )
    client.force_login(user)

    response = client.get(reverse("control:3d_pricing"))
    assert response.status_code == 200

    response = client.post(
        reverse("control:3d_pricing"),
        {
            "tshirt_base_price": 800000,
            "customer_label_price": 150000,
        },
    )
    assert response.status_code == 302
    pricing = CustomizerPricingSettings.get_solo()
    assert pricing.tshirt_base_price == 800000
    assert pricing.customer_label_price == 150000


def test_two_non_overlapping_labels_on_same_side_are_accepted(product, configured_designer):
    _, area, artwork = configured_designer
    payload = {
        "version": 1,
        "layers": [
            {"artwork_id": artwork.id, "area_id": area.id, "side": "front", "x": .25, "y": .5, "width": .3, "height": .3, "rotation": 0},
            {"artwork_id": artwork.id, "area_id": area.id, "side": "front", "x": .75, "y": .5, "width": .3, "height": .3, "rotation": 0},
        ],
    }

    normalized, _ = validate_design_payload(product, payload)
    assert len(normalized["layers"]) == 2


def test_front_and_back_layers_are_independent(product, configured_designer):
    view, area, artwork = configured_designer
    back_view = DesignerView.objects.create(
        product=product,
        key="back",
        name="پشت",
        background_image=SimpleUploadedFile("shirt-back.png", PNG_1X1, content_type="image/png"),
        canvas_width=1000,
        canvas_height=1000,
    )
    PrintAreaView.objects.create(
        area=area,
        view=back_view,
        geometry=[
            {"x": 0.30, "y": 0.25},
            {"x": 0.55, "y": 0.25},
            {"x": 0.55, "y": 0.50},
            {"x": 0.30, "y": 0.50},
        ],
    )

    payload = {
        "version": 1,
        "layers": [
            {"artwork_id": artwork.id, "area_id": area.id, "side": "front", "x": .5, "y": .5, "width": .3, "height": .3, "rotation": 0},
            {"artwork_id": artwork.id, "area_id": area.id, "side": "back", "x": .5, "y": .5, "width": .3, "height": .3, "rotation": 0},
        ],
    }

    normalized, _ = validate_design_payload(product, payload)
    assert len(normalized["layers"]) == 2
    assert {layer["side"] for layer in normalized["layers"]} == {"front", "back"}


def test_design_payload_rejects_outside_and_overlap(product, configured_designer):
    _, area, artwork = configured_designer
    outside = {"version": 1, "layers": [{"artwork_id": artwork.id, "area_id": area.id, "x": .5, "y": .5, "width": 1.1, "height": .3, "rotation": 0}]}
    with pytest.raises(ValidationError):
        validate_design_payload(product, outside)

    overlap = {"version": 1, "layers": [
        {"artwork_id": artwork.id, "area_id": area.id, "x": .35, "y": .5, "width": .3, "height": .3, "rotation": 0},
        {"artwork_id": artwork.id, "area_id": area.id, "x": .45, "y": .5, "width": .3, "height": .3, "rotation": 0},
    ]}
    with pytest.raises(ValidationError):
        validate_design_payload(product, overlap)


def test_variant_must_be_in_stock_when_selected(product, configured_designer):
    _, area, artwork = configured_designer
    color = ProductColor.objects.create(name="مشکی", slug="black", hex_code="#000000")
    size = ProductSize.objects.create(name="L", slug="l")
    variant = ProductVariant.objects.create(product=product, color=color, size=size, sku="BLACK-L", price=550000, stock_quantity=0)
    payload = {"version": 1, "layers": [{"artwork_id": artwork.id, "area_id": area.id, "x": .5, "y": .5, "width": .3, "height": .3, "rotation": 0}]}
    with pytest.raises(ValidationError):
        validate_design_payload(product, payload, variant=variant)


def test_variant_is_required_if_product_has_variants(product, configured_designer):
    _, area, artwork = configured_designer
    color = ProductColor.objects.create(name="مشکی", slug="black", hex_code="#000000")
    size = ProductSize.objects.create(name="L", slug="l")
    ProductVariant.objects.create(product=product, color=color, size=size, sku="BLACK-L", price=550000, stock_quantity=5)
    payload = {"version": 1, "layers": [{"artwork_id": artwork.id, "area_id": area.id, "x": .5, "y": .5, "width": .3, "height": .3, "rotation": 0}]}
    with pytest.raises(ValidationError):
        validate_design_payload(product, payload)


def test_designer_page_and_save_endpoint(client, product, configured_designer):
    response = client.get(reverse("customizer:designer", kwargs={"product_ref": str(product.uuid)}))
    assert response.status_code == 200

    _, area, artwork = configured_designer
    payload = {"variant_id": None, "version": 1, "layers": [{"artwork_id": artwork.id, "area_id": area.id, "x": .5, "y": .5, "width": .3, "height": .3, "rotation": 0}]}
    save = client.post(reverse("customizer:save_design", kwargs={"slug": product.slug}), data=json.dumps(payload), content_type="application/json")
    assert save.status_code == 200
    assert DesignDraft.objects.filter(product=product).exists()



@pytest.mark.django_db
def test_customer_uploads_with_same_filename_do_not_collide(client, configured_designer, tmp_path):
    product = configured_designer[0].product
    media_root = tmp_path / "media"
    temp_root = tmp_path / "customizer_tmp"

    with override_settings(MEDIA_ROOT=media_root, CUSTOMIZER_TEMP_ROOT=temp_root):
        url = reverse("customizer:upload_artwork", kwargs={"slug": product.slug})
        image = make_valid_png()

        first = client.post(
            url,
            {"image": SimpleUploadedFile("logo.png", image, content_type="image/png")},
        )
        second = client.post(
            url,
            {"image": SimpleUploadedFile("logo.png", image, content_type="image/png")},
        )

        assert first.status_code == 200
        assert second.status_code == 200

        uploads = Artwork.objects.filter(source=Artwork.Source.UPLOAD).order_by("id")
        assert uploads.count() == 2
        assert uploads[0].slug != uploads[1].slug

        for artwork in uploads:
            assert not artwork.image.name
            assert artwork.temp_image_path
            assert (temp_root / artwork.temp_image_path).is_file()

        assert not any(media_root.rglob("*"))


@pytest.mark.django_db
def test_customer_upload_does_not_write_to_media(client, configured_designer, tmp_path):
    product = configured_designer[0].product
    media_root = tmp_path / "media"
    temp_root = tmp_path / "customizer_tmp"

    with override_settings(MEDIA_ROOT=media_root, CUSTOMIZER_TEMP_ROOT=temp_root):
        response = client.post(
            reverse("customizer:upload_artwork", kwargs={"slug": product.slug}),
            {
                "image": SimpleUploadedFile(
                    "transparent-logo.png",
                    make_valid_png(),
                    content_type="image/png",
                )
            },
        )

        assert response.status_code == 200
        artwork = Artwork.objects.get(source=Artwork.Source.UPLOAD)
        assert artwork.image.name == ""
        assert artwork.temp_image_path
        assert (temp_root / artwork.temp_image_path).is_file()
        assert "artwork_temp_image" in response.json()["artwork"]["image"]


def test_customer_upload_access_is_private(client, configured_designer, tmp_path):
    product = configured_designer[0].product
    media_root = tmp_path / "media"
    temp_root = tmp_path / "customizer_tmp"

    with override_settings(MEDIA_ROOT=media_root, CUSTOMIZER_TEMP_ROOT=temp_root):
        response = client.post(
            reverse("customizer:upload_artwork", kwargs={"slug": product.slug}),
            {
                "image": SimpleUploadedFile(
                    "private.png",
                    make_valid_png(),
                    content_type="image/png",
                )
            },
        )
        assert response.status_code == 200
        image_url = response.json()["artwork"]["image"]

        other = Client()
        forbidden = other.get(image_url)
        assert forbidden.status_code in {403, 404}
