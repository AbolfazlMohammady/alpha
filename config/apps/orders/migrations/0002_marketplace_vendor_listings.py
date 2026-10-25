from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        # custom_design is introduced by the parallel order migration, so it
        # must exist in the project state before constraints reference it.
        ("orders", "0003_custom_design_cart_order"),
        ("marketplace", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cartitem",
            name="vendor_listing",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="cart_items", to="marketplace.vendorproduct"),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="vendor_listing",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="order_items", to="marketplace.vendorproduct"),
        ),
        migrations.RemoveConstraint(model_name="cartitem", name="unique_cart_variant_item"),
        migrations.RemoveConstraint(model_name="cartitem", name="unique_cart_product_item"),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(condition=models.Q(("variant__isnull", False), ("custom_design__isnull", True), ("vendor_listing__isnull", True)), fields=("cart", "variant"), name="unique_cart_variant_item"),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(condition=models.Q(("variant__isnull", False), ("custom_design__isnull", True), ("vendor_listing__isnull", False)), fields=("cart", "variant", "vendor_listing"), name="unique_cart_vendor_variant_item"),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(condition=models.Q(("variant__isnull", True), ("custom_design__isnull", True), ("vendor_listing__isnull", True)), fields=("cart", "product"), name="unique_cart_product_item"),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(condition=models.Q(("variant__isnull", True), ("custom_design__isnull", True), ("vendor_listing__isnull", False)), fields=("cart", "product", "vendor_listing"), name="unique_cart_vendor_product_item"),
        ),
    ]
