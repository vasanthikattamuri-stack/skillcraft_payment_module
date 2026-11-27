"""
URL configuration for the STANDALONE DEMO project.

Only two things live here:
  1. The reusable payments app, mounted at /api/payments/
  2. JWT login endpoints used to obtain an `access_token` for Postman testing.

In the main SkillCraft.AI project you only need the `payments` include line;
the main project already has its own authentication endpoints.
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Demo-only authentication endpoints (POST username + password -> JWT).
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # The reusable payments module.
    path("api/payments/", include("payments.urls")),
]
