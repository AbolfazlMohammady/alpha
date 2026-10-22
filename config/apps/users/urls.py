from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/verify/", views.verify_otp_view, name="verify_otp"),
    path("logout/", views.logout_view, name="logout"),

    path("account/", views.profile_view, name="profile"),
    path("account/profile/", views.profile_update_view, name="profile_update"),

    path("account/addresses/", views.addresses_view, name="addresses"),
    path("account/addresses/add/", views.address_create_view, name="address_create"),
    path("account/addresses/<int:pk>/edit/", views.address_update_view, name="address_update"),
    path("account/addresses/<int:pk>/delete/", views.address_delete_view, name="address_delete"),
]