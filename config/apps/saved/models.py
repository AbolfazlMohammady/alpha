from django.conf import settings
from django.db import models


class FavoriteProduct(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_products")
    product = models.ForeignKey("shop.Product", on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "product"), name="unique_favorite_product"),
        ]
        indexes = [models.Index(fields=("user", "-created_at"))]

    def __str__(self):
        return f"{self.user} ♥ {self.product}"

