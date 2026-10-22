from django.urls import path

from . import views

app_name = "saved"

urlpatterns = [
    path("favorite/<int:product_id>/", views.toggle_favorite, name="toggle_favorite"),
    path("account/saved/", views.saved_page, name="saved"),
]
