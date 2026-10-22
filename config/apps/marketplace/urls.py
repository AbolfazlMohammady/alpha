from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("api/shipping/quote/", views.cart_shipping_quote_api, name="cart_shipping_quote_api"),
    path("api/vendor/dashboard/", views.vendor_dashboard_api, name="vendor_dashboard_api"),
    path("api/vendor/products/", views.vendor_products_api, name="vendor_products_api"),
    path("api/vendor/products/<int:listing_id>/", views.vendor_product_update_api, name="vendor_product_update_api"),
    path("api/vendor/products/<int:listing_id>/wholesale/", views.vendor_wholesale_tier_api, name="vendor_wholesale_tier_api"),
    path("api/vendor/wholesale/<int:tier_id>/delete/", views.vendor_wholesale_tier_delete_api, name="vendor_wholesale_tier_delete_api"),
    path("api/vendor/categories/request/", views.vendor_category_request_api, name="vendor_category_request_api"),
    path("api/vendor/orders/<int:order_id>/action/", views.vendor_order_action_api, name="vendor_order_action_api"),
    path("api/vendor/orders/<int:order_id>/shipping/quote/", views.shipment_quote_api, name="shipment_quote_api"),
    path("api/vendor/orders/<int:order_id>/shipping/book/", views.shipment_book_api, name="shipment_book_api"),
    path("api/vendor/orders/<int:order_id>/shipping/<uuid:shipment_uuid>/handed-over/", views.shipment_handed_over_api, name="shipment_handed_over_api"),
    path("api/admin/shipping/<uuid:shipment_uuid>/status/", views.shipment_update_status_api, name="shipment_update_status_api"),
    path("api/admin/accounting/trial-balance/", views.trial_balance_api, name="trial_balance_api"),
    path("api/admin/accounting/reconciliation/", views.external_reconciliation_api, name="external_reconciliation_api"),
    path("api/admin/accounting/carrier-payment/", views.carrier_invoice_payment_api, name="carrier_invoice_payment_api"),
    path("api/admin/accounting/gateway-settlement/", views.gateway_settlement_api, name="gateway_settlement_api"),
    path("api/admin/settlements/", views.settlement_queue_api, name="settlement_queue_api"),
    path("api/admin/settlements/<int:batch_id>/approve/", views.settlement_approve_api, name="settlement_approve_api"),
    path("api/admin/settlements/<int:batch_id>/payout-result/", views.settlement_record_payout_api, name="settlement_record_payout_api"),
]
