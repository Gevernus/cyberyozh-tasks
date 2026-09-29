from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from config.health import LivenessView, ReadinessView
from config.metrics import metrics_view

urlpatterns = [
    path("api/health/", ReadinessView.as_view(), name="health"),
    path("api/health/live/", LivenessView.as_view(), name="health-live"),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.tasks.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("metrics", metrics_view, name="metrics"),
]

if settings.ADMIN_ENABLED:
    urlpatterns.append(path(settings.ADMIN_URL, admin.site.urls))
