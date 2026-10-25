from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve
from apps.shop.sitemaps import sitemaps


def robots_txt(request):
    content = "\n".join([
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /login/",
        "Disallow: /register/",
        "Disallow: /logout/",
        "",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml"
    ])
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", robots_txt, name="robots"),
    path("admin/", admin.site.urls),
    path("control/", include("apps.control_center.urls")),
    path("shop/", include("apps.shop.urls")),
    path("customizer/", include("apps.customizer.urls")),
    path("marketplace/", include("apps.marketplace.urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.home.urls")),
    path("", include("apps.users.urls")),
    path("", include("apps.saved.urls")),
]

# Django's static() helper intentionally returns no URL patterns when
# DEBUG=False. Product uploads live under MEDIA_URL, so keep an explicit
# fallback route for Gunicorn/local staging where Nginx is not in front.
# In production Nginx should serve /media/ directly from MEDIA_ROOT.
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve,
        {"document_root": settings.MEDIA_ROOT},
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
