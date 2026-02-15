from django.contrib import admin
from django.utils.html import format_html
from .models import Ride, RideStatusLog


class RideStatusLogInline(admin.TabularInline):
    model = RideStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "note", "timestamp")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = (
        "short_id", "rider_name", "driver_name",
        "pickup_address", "dropoff_address",
        "price_display", "status_badge", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "rider__full_name", "rider__phone_number",
        "driver__full_name",
        "pickup_address", "dropoff_address",
    )
    readonly_fields = (
        "id", "price", "assigned_at", "started_at",
        "completed_at", "cancelled_at", "created_at", "updated_at",
    )
    ordering = ("-created_at",)
    inlines = [RideStatusLogInline]

    fieldsets = (
        ("Ride Info", {
            "fields": ("id", "rider", "driver", "price", "status")
        }),
        ("Pickup", {
            "fields": ("pickup_address", "pickup_lat", "pickup_lng")
        }),
        ("Dropoff", {
            "fields": ("dropoff_address", "dropoff_lat", "dropoff_lng")
        }),
        ("Assignment", {
            "fields": ("assigned_by", "assigned_at")
        }),
        ("Cancellation", {
            "fields": ("cancelled_by", "cancelled_at", "cancellation_reason")
        }),
        ("Lifecycle", {
            "fields": ("started_at", "completed_at", "created_at", "updated_at")
        }),
        ("Notes", {"fields": ("rider_notes",)}),
    )

    def short_id(self, obj):
        return str(obj.id)[:8].upper()
    short_id.short_description = "ID"

    def rider_name(self, obj):
        return obj.rider.full_name
    rider_name.short_description = "Rider"

    def driver_name(self, obj):
        return obj.driver.full_name if obj.driver else "—"
    driver_name.short_description = "Driver"

    def price_display(self, obj):
        return f"₦{obj.price:,}"
    price_display.short_description = "Price"

    def status_badge(self, obj):
        colors = {
            "REQUESTED": "#f0ad4e",
            "ASSIGNED": "#337ab7",
            "IN_PROGRESS": "#5bc0de",
            "COMPLETED": "#5cb85c",
            "CANCELLED": "#d9534f",
        }
        color = colors.get(obj.status, "#aaa")
        return format_html(
            '<span style="background:{};color:#fff;padding:3px 8px;border-radius:4px;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Status"


@admin.register(RideStatusLog)
class RideStatusLogAdmin(admin.ModelAdmin):
    list_display = ("ride_short", "from_status", "to_status", "changed_by", "timestamp")
    list_filter = ("to_status", "timestamp")
    readonly_fields = ("id", "ride", "from_status", "to_status", "changed_by", "note", "timestamp")
    ordering = ("-timestamp",)

    def ride_short(self, obj):
        return str(obj.ride_id)[:8].upper()
    ride_short.short_description = "Ride ID"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False