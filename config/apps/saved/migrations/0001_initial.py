from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("shop", "0004_alter_productsize_slug_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FavoriteProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favorited_by", to="shop.product")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favorite_products", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="SavedProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_by", to="shop.product")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_products", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="favoriteproduct",
            constraint=models.UniqueConstraint(fields=("user", "product"), name="unique_favorite_product"),
        ),
        migrations.AddConstraint(
            model_name="savedproduct",
            constraint=models.UniqueConstraint(fields=("user", "product"), name="unique_saved_product"),
        ),
        migrations.AddIndex(
            model_name="favoriteproduct",
            index=models.Index(fields=("user", "-created_at"), name="saved_favor_user_id_8d8f4d_idx"),
        ),
        migrations.AddIndex(
            model_name="savedproduct",
            index=models.Index(fields=("user", "-created_at"), name="saved_save_user_id_2c4b3d_idx"),
        ),
    ]
