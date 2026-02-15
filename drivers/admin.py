from django.contrib import admin
from django.utils.html import format_html
from .models import DriverApplication, Bike


@admin.register(DriverApplication)
class DriverApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "applicant_name", "applicant_phone", "status_badge",
        "reviewed_by", "reviewed_at", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "applicant__full_name", "applicant__email", "applicant__phone_number"
    )
    readonly_fields = ("id", "created_at", "updated_at", "reviewed_at")
    ordering = ("-created_at",)

    fieldsets = (
        ("Application", {
            "fields": (
                "id", "applicant", "resume",
                "guarantor_name", "guarantor_phone",
                "years_of_experience", "additional_notes",
            )
        }),
        ("Review", {
            "fields": ("status", "reviewed_by", "reviewed_at", "rejection_reason")
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    

    def applicant_name(self, obj):
        return obj.applicant.full_name
    applicant_name.short_description = "Applicant"

    def applicant_phone(self, obj):
        return obj.applicant.phone_number
    applicant_phone.short_description = "Phone"

    def status_badge(self, obj):
        colors = {
            "pending": "#f0ad4e",
            "accepted": "#5cb85c",
            "rejected": "#d9534f",
        }
        color = colors.get(obj.status, "#aaa")
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 8px;border-radius:4px;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"


@admin.register(Bike)
class BikeAdmin(admin.ModelAdmin):
    list_display = (
        "license_plate", "bike_type", "driver_name",
        "status_badge", "assigned_at", "created_at",
    )
    list_filter = ("status", "bike_type", "created_at")
    search_fields = ("license_plate", "model", "driver__full_name")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)

    def driver_name(self, obj):
        return obj.driver.full_name if obj.driver else "—"
    driver_name.short_description = "Driver"

    def status_badge(self, obj):
        colors = {
            "available": "#5cb85c",
            "in_use": "#337ab7",
            "maintenance": "#f0ad4e",
            "retired": "#d9534f",
        }
        color = colors.get(obj.status, "#aaa")
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 8px;border-radius:4px;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"