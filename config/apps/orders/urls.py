from django.urls import path

from .views import (
    cart_add_view,
    custom_design_cart_add_view,
    cart_clear_view,
    cart_remove_view,
    cart_update_view,
    cart_view,
    checkout_view,
    invoice_view,
    order_detail_view,
    order_payment_view,
    orders_list_view,
)


app_name = "orders"

urlpatterns = [
    path("orders/", orders_list_view, name="list"),
    path("orders/checkout/", checkout_view, name="checkout"),
    path("orders/<uuid:order_uuid>/", order_detail_view, name="detail"),
    path("orders/<uuid:order_uuid>/payment/", order_payment_view, name="payment"),
    path("orders/<uuid:order_uuid>/invoice/", invoice_view, name="invoice"),

    path("cart/", cart_view, name="cart"),
    path("cart/add/", cart_add_view, name="cart_add"),
    path("cart/custom-design/<slug:slug>/add/", custom_design_cart_add_view, name="custom_design_cart_add"),
    path("cart/<int:item_id>/update/", cart_update_view, name="cart_update"),
    path("cart/<int:item_id>/remove/", cart_remove_view, name="cart_remove"),
    path("cart/clear/", cart_clear_view, name="cart_clear"),
]
