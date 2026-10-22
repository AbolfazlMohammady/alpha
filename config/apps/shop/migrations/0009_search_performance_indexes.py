from django.db import migrations


INDEXES = (
    (
        "shop_product_name_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_product_name_trgm_idx "
        "ON shop_product USING gin (name gin_trgm_ops)",
    ),
    (
        "shop_product_slug_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_product_slug_trgm_idx "
        "ON shop_product USING gin (slug gin_trgm_ops)",
    ),
    (
        "shop_product_short_desc_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_product_short_desc_trgm_idx "
        "ON shop_product USING gin (short_description gin_trgm_ops)",
    ),
    (
        "shop_product_desc_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_product_desc_trgm_idx "
        "ON shop_product USING gin (description gin_trgm_ops)",
    ),
    (
        "shop_product_seo_title_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_product_seo_title_trgm_idx "
        "ON shop_product USING gin (seo_title gin_trgm_ops)",
    ),
    (
        "shop_product_seo_desc_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_product_seo_desc_trgm_idx "
        "ON shop_product USING gin (seo_description gin_trgm_ops)",
    ),
    (
        "shop_category_name_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_category_name_trgm_idx "
        "ON shop_category USING gin (name gin_trgm_ops)",
    ),
    (
        "shop_variant_sku_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_variant_sku_trgm_idx "
        "ON shop_productvariant USING gin (sku gin_trgm_ops)",
    ),
    (
        "shop_color_name_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_color_name_trgm_idx "
        "ON shop_productcolor USING gin (name gin_trgm_ops)",
    ),
    (
        "shop_size_name_trgm_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_size_name_trgm_idx "
        "ON shop_productsize USING gin (name gin_trgm_ops)",
    ),
    (
        "shop_variant_active_price_product_idx",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS shop_variant_active_price_product_idx "
        "ON shop_productvariant (is_active, price, product_id)",
    ),
)


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for _name, sql in INDEXES:
            cursor.execute(sql)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        for name, _sql in reversed(INDEXES):
            cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("shop", "0008_merge_20261002_1258"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
