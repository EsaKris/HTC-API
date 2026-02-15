from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "phone_number", "full_name", "email", "role",
        "is_active", "is_staff", "created_at",
    )
    list_filter = ("role", "is_active", "is_staff", "created_at")
    search_fields = ("phone_number", "email", "full_name")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "otp_expires_at")

    fieldsets = (
        (None, {"fields": ("id", "phone_number", "password")}),
        (_("Personal Info"), {"fields": ("full_name", "email")}),
        (_("Roles & Permissions"), {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("OTP Info"), {"fields": ("otp_code", "otp_expires_at", "otp_purpose", "otp_attempts")}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "phone_number", "email", "full_name",
                    "role", "password1", "password2",
                ),
            },
        ),
    )

    USERNAME_FIELD = "phone_number"