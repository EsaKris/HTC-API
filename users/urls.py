from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RegisterView,
    LoginRequestOTPView,
    VerifyOTPView,
    ForgotPasswordView,
    ResetPasswordView,
    LogoutView,
    MeView,
)

urlpatterns = [
    # Registration
    path("register/", RegisterView.as_view(), name="auth-register"),

    # Login flow (2-step OTP)
    path("login/", LoginRequestOTPView.as_view(), name="auth-login"),
    path("verify-otp/", VerifyOTPView.as_view(), name="auth-verify-otp"),

    # Token refresh (handled by simplejwt)
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),

    # Password management
    path("forgot-password/", ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("reset-password/", ResetPasswordView.as_view(), name="auth-reset-password"),

    # Session
    path("logout/", LogoutView.as_view(), name="auth-logout"),

    # Authenticated user profile
    path("me/", MeView.as_view(), name="auth-me"),
]