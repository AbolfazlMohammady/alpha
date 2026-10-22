from django.urls import path, re_path

from .views import CategoryDetailView, ContactPageView, ProductCommentAddView, ProductCommentsView, ProductDetailView, ShopIndexView, ShopSearchView


app_name = "shop"

urlpatterns = [
    path("", ShopIndexView.as_view(), name="index"),
    path("contact/", ContactPageView.as_view(), name="contact"),
    path("search/", ShopSearchView.as_view(), name="search"),
    re_path(r"^category/(?P<slug>[^/]+)/$", CategoryDetailView.as_view(), name="category"),
    re_path(r"^product/(?P<slug>[^/]+)/$", ProductDetailView.as_view(), name="product"),
    re_path(r"^product/(?P<slug>[^/]+)/comments/$", ProductCommentsView.as_view(), name="product_comments"),
    re_path(r"^product/(?P<slug>[^/]+)/comments/add/$", ProductCommentAddView.as_view(), name="product_comment_add"),
]
