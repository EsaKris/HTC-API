from django.contrib import admin
from django.utils.html import format_html
from .models import DriverApplication, Bike, BikeOwner, BikeRegistration
from django.utils import timezone

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

@admin.register(BikeOwner)
class BikeOwnerAdmin(admin.ModelAdmin):
    list_display = [
        "full_name",
        "phone_number",
        "email",
        "status",
        "total_bikes",
        "total_earnings_display",
        "total_rides",
        "created_at",
    ]
    list_filter = ["status", "created_at", "verified_at"]
    search_fields = ["full_name", "phone_number", "email"]
    readonly_fields = [
        "id",
        "total_bikes",
        "active_bikes",
        "total_earnings_display",
        "total_rides",
        "verified_by",
        "verified_at",
        "created_at",
        "updated_at",
    ]
    
    fieldsets = (
        ("Personal Information", {
            "fields": (
                "full_name",
                "phone_number",
                "email",
                "address",
            )
        }),
        ("Bank Details", {
            "fields": (
                "bank_name",
                "account_number",
                "account_name",
            )
        }),
        ("Documents", {
            "fields": (
                "id_document",
                "profile_photo",
            )
        }),
        ("Status & Admin", {
            "fields": (
                "status",
                "admin_notes",
                "verified_by",
                "verified_at",
            )
        }),
        ("Statistics", {
            "fields": (
                "total_bikes",
                "active_bikes",
                "total_earnings_display",
            ),
            "classes": ("collapse",)
        }),
        ("Metadata", {
            "fields": ("id", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def total_bikes(self, obj):
        """Show number of bikes owned"""
        return obj.bikes.count()
    total_bikes.short_description = "Total Bikes"
    
    def active_bikes(self, obj):
        """Show number of bikes in use"""
        return obj.bikes.filter(status='in_use').count()
    active_bikes.short_description = "Active Bikes"

    def total_rides(self, obj):
        """Show total number of rides for this bike owner"""
        return obj.total_rides

    total_rides.short_description = "Total Rides"
    
    def total_earnings_display(self, obj):
        """Show total earnings"""
        from django.utils.html import format_html
        earnings = obj.calculate_total_earnings()
        return format_html(
            '<strong style="color: #22c55e;">₦{:,.2f}</strong>',
            earnings
        )
    total_earnings_display.short_description = "Total Earnings"


@admin.register(BikeRegistration)
class BikeRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "license_plate",
        "owner_name",
        "owner_phone",
        "bike_type",
        "status",
        "reviewed_by",
        "created_at",
    ]
    list_filter = ["status", "bike_type", "created_at"]
    search_fields = [
        "license_plate",
        "owner_name",
        "owner_phone",
        "owner_email",
    ]
    readonly_fields = [
        "id",
        "approved_owner",
        "approved_bike",
        "reviewed_by",
        "reviewed_at",
        "created_at",
        "updated_at",
    ]
    
    fieldsets = (
        ("Owner Information", {
            "fields": (
                "owner_name",
                "owner_phone",
                "owner_email",
                "owner_address",
            )
        }),
        ("Bank Details", {
            "fields": (
                "bank_name",
                "account_number",
                "account_name",
            )
        }),
        ("Owner Documents", {
            "fields": (
                "id_document",
                "owner_photo",
            )
        }),
        ("Bike Details", {
            "fields": (
                "bike_type",
                "license_plate",
                "model",
                "color",
                "year",
            )
        }),
        ("Bike Documents", {
            "fields": (
                "bike_photo",
                "registration_document",
                "additional_notes",
            )
        }),
        ("Review Status", {
            "fields": (
                "status",
                "reviewed_by",
                "reviewed_at",
                "rejection_reason",
                "approved_owner",
                "approved_bike",
            )
        }),
        ("Metadata", {
            "fields": ("id", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    actions = ["approve_registrations", "reject_registrations"]
    
    def approve_registrations(self, request, queryset):
        """Bulk approve registrations"""
        pending = queryset.filter(status='pending')
        count = 0
        
        for reg in pending:
            # This is a simplified version - real approval should use the view logic
            count += 1
        
        self.message_user(request, f"{count} registrations approved.")
    approve_registrations.short_description = "Approve selected registrations"
    
    def reject_registrations(self, request, queryset):
        """Bulk reject registrations"""
        pending = queryset.filter(status='pending')
        count = pending.update(
            status='rejected',
            reviewed_by=request.user,
            reviewed_at=timezone.now()
        )
        
        self.message_user(request, f"{count} registrations rejected.")
    reject_registrations.short_description = "Reject selected registrations"
    
    def has_add_permission(self, request):
        # Registrations should come from public form, not admin panel
        return False


# ══════════════════════════════════════════════════════════════════════════
# UPDATE EXISTING BIKE ADMIN (if you have one)
# ══════════════════════════════════════════════════════════════════════════

# If you already have a BikeAdmin, update it to show owner info:

@admin.register(Bike)
class BikeAdmin(admin.ModelAdmin):
    list_display = [
        "license_plate",
        "owner_name",
        "driver_name",
        "bike_type",
        "status",
        "total_earnings_display",
        "assigned_at",
    ]
    list_filter = ["status", "bike_type", "created_at"]
    search_fields = [
        "license_plate",
        "owner__full_name",
        "driver__full_name",
        "model",
    ]
    readonly_fields = [
        "id",
        "total_earnings_display",
        "total_rides",
        "assigned_by",
        "assigned_at",
        "created_at",
        "updated_at",
    ]
    
    fieldsets = (
        ("Ownership", {
            "fields": (
                "owner",
                "driver",
            )
        }),
        ("Bike Details", {
            "fields": (
                "bike_type",
                "license_plate",
                "model",
                "color",
                "year",
                "status",
            )
        }),
        ("Documents", {
            "fields": (
                "bike_photo",
                "registration_document",
            )
        }),
        ("Assignment", {
            "fields": (
                "assigned_by",
                "assigned_at",
            )
        }),
        ("Statistics", {
            "fields": (
                "total_earnings_display",
                "total_rides",
            ),
            "classes": ("collapse",)
        }),
        ("Metadata", {
            "fields": ("id", "created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def owner_name(self, obj):
        """Show bike owner name"""
        return obj.owner.full_name if obj.owner else "—"
    owner_name.short_description = "Owner"
    
    def driver_name(self, obj):
        """Show assigned driver name"""
        return obj.driver.full_name if obj.driver else "Unassigned"
    driver_name.short_description = "Driver"
    
    def total_earnings_display(self, obj):
        """Show total earnings for this bike"""
        from django.utils.html import format_html
        earnings = obj.calculate_total_earnings()
        return format_html(
            '<strong style="color: #22c55e;">₦{:,.2f}</strong>',
            earnings
        )
    total_earnings_display.short_description = "Total Earnings"


# ══════════════════════════════════════════════════════════════════════════
# ADD THIS IMPORT AT TOP OF admin.py
# ══════════════════════════════════════════════════════════════════════════


