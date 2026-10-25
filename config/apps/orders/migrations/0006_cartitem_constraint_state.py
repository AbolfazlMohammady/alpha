from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0005_merge_marketplace_custom_design"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="cartitem",
            name="unique_cart_variant_item",
        ),
        migrations.RemoveConstraint(
            model_name="cartitem",
            name="unique_cart_vendor_variant_item",
        ),
        migrations.RemoveConstraint(
            model_name="cartitem",
            name="unique_cart_product_item",
        ),
        migrations.RemoveConstraint(
            model_name="cartitem",
            name="unique_cart_vendor_product_item",
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("custom_design__isnull", True), ("variant__isnull", False), ("vendor_listing__isnull", True)),
                fields=("cart", "variant"),
                name="unique_cart_variant_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("custom_design__isnull", True), ("variant__isnull", False), ("vendor_listing__isnull", False)),
                fields=("cart", "variant", "vendor_listing"),
                name="unique_cart_vendor_variant_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("custom_design__isnull", True), ("variant__isnull", True), ("vendor_listing__isnull", True)),
                fields=("cart", "product"),
                name="unique_cart_product_item",
            ),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("custom_design__isnull", True), ("variant__isnull", True), ("vendor_listing__isnull", False)),
                fields=("cart", "product", "vendor_listing"),
                name="unique_cart_vendor_product_item",
            ),
        ),
    ]
