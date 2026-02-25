from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import DriverApplication, Bike, BikeOwner, BikeRegistration 

User = get_user_model()


# ---------------------------------------------------------------------------
# Application serializers
# ---------------------------------------------------------------------------

class DriverApplicationCreateSerializer(serializers.ModelSerializer):
    """
    Used by a rider/user to submit a driver application.
    The applicant is set from the authenticated request user.
    """

    class Meta:
        model = DriverApplication
        fields = [
            "id",
            "resume",
            "guarantor_name",
            "guarantor_phone",
            "years_of_experience",
            "additional_notes",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        # Prevent duplicate applications
        if DriverApplication.objects.filter(applicant=user).exists():
            raise serializers.ValidationError(
                "You already have a driver application on file."
            )
        # Must not already be a driver
        if user.role == User.Role.DRIVER:
            raise serializers.ValidationError("You are already a registered driver.")
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        # Flip role to pending_driver while application is open
        user.role = User.Role.PENDING_DRIVER
        user.save(update_fields=["role"])
        return DriverApplication.objects.create(applicant=user, **validated_data)


class ApplicantSummarySerializer(serializers.ModelSerializer):
    """Compact user info embedded in application responses."""

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "phone_number", "role"]


class DriverApplicationListSerializer(serializers.ModelSerializer):
    """Admin list view — includes applicant details."""

    applicant = ApplicantSummarySerializer(read_only=True)
    reviewed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = DriverApplication
        fields = [
            "id",
            "applicant",
            "resume",
            "guarantor_name",
            "guarantor_phone",
            "years_of_experience",
            "additional_notes",
            "status",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]


class DriverApplicationDetailSerializer(DriverApplicationListSerializer):
    """Full application detail — same as list for now, easily extended."""
    pass


class ApproveApplicationSerializer(serializers.Serializer):
    """Admin approves a driver application. No additional body required."""
    pass


class RejectApplicationSerializer(serializers.Serializer):
    """Admin rejects a driver application — optionally with a reason."""

    rejection_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Optional reason shown to the applicant.",
    )


# ---------------------------------------------------------------------------
# Bike serializers
# ---------------------------------------------------------------------------

class BikeSerializer(serializers.ModelSerializer):
    """Full bike representation (admin view)."""

    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    owner_phone = serializers.CharField(source="owner.phone_number", read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    
    driver_name = serializers.CharField(
        source="driver.full_name", read_only=True, allow_null=True
    )
    driver_phone = serializers.CharField(
        source="driver.phone_number", read_only=True, allow_null=True
    )
    
    assigned_by_name = serializers.CharField(
        source="assigned_by.full_name", read_only=True, allow_null=True
    )
    
    total_earnings = serializers.SerializerMethodField()
    total_rides = serializers.IntegerField(read_only=True)

    class Meta:
        model = Bike
        fields = [
            "id",
            "owner",
            "owner_name",
            "owner_phone",
            "owner_email",
            "driver",
            "driver_name",
            "driver_phone",
            "bike_type",
            "license_plate",
            "model",
            "color",
            "year",
            "status",
            "bike_photo",
            "registration_document",
            "assigned_by",
            "assigned_by_name",
            "assigned_at",
            "total_earnings",
            "total_rides",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "assigned_by",
            "assigned_at",
            "created_at",
            "updated_at",
        ]
    def get_driver_name(self, obj):
        return obj.driver.full_name if obj.driver else None

    def get_assigned_by_name(self, obj):
        return obj.assigned_by.full_name if obj.assigned_by else None
   
    def get_total_earnings(self, obj):
        """Calculate earnings for this bike"""
        return obj.calculate_total_earnings()


class BikeCreateSerializer(serializers.ModelSerializer):
    """Admin creates a new bike record (unassigned)."""

    class Meta:
        model = Bike
        fields = [
            "id",
            "bike_type",
            "license_plate",
            "model",
            "color",
            "year",
            "status",
        ]
        read_only_fields = ["id"]

    def validate_license_plate(self, value):
        return value.strip().upper()


class AssignBikeSerializer(serializers.Serializer):
    """Admin assigns an existing unassigned bike to a driver."""

    driver_id = serializers.UUIDField(help_text="UUID of the approved driver.")

    def validate_driver_id(self, value):
        try:
            driver = User.objects.get(id=value, role=User.Role.DRIVER, is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError("Driver not found or not an active approved driver.")
        # Check the driver doesn't already have a bike
        if hasattr(driver, "assigned_bike") and driver.assigned_bike is not None:
            raise serializers.ValidationError(
                f"Driver '{driver.full_name}' already has a bike assigned. "
                "Unassign the current bike first."
            )
        return value


class DriverProfileSerializer(serializers.ModelSerializer):
    """Public driver profile including their bike details."""

    bike = BikeSerializer(source="assigned_bike", read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "phone_number", "role", "bike"]


# ══════════════════════════════════════════════════════════════════════════
# BIKE OWNER SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════

class BikeOwnerSerializer(serializers.ModelSerializer):
    """Basic bike owner info"""
    
    total_bikes = serializers.IntegerField(read_only=True)
    active_bikes = serializers.IntegerField(read_only=True)
    verified_by_name = serializers.CharField(
        source="verified_by.full_name", read_only=True, allow_null=True
    )
    
    class Meta:
        model = BikeOwner
        fields = [
            "id",
            "full_name",
            "phone_number",
            "email",
            "address",
            "status",
            "total_bikes",
            "active_bikes",
            "verified_by_name",
            "verified_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "verified_by",
            "verified_at",
            "created_at",
        ]


class BikeOwnerDetailSerializer(serializers.ModelSerializer):
    """
    Full bike owner profile with earnings and bank details.
    Admin only.
    """
    
    total_bikes = serializers.IntegerField(read_only=True)
    active_bikes = serializers.IntegerField(read_only=True)
    total_earnings = serializers.SerializerMethodField()
    earnings_by_bike = serializers.SerializerMethodField()
    verified_by_name = serializers.CharField(
        source="verified_by.full_name", read_only=True, allow_null=True
    )
    
    class Meta:
        model = BikeOwner
        fields = [
            "id",
            "full_name",
            "phone_number",
            "email",
            "address",
            "bank_name",
            "account_number",
            "account_name",
            "id_document",
            "profile_photo",
            "status",
            "admin_notes",
            "total_bikes",
            "active_bikes",
            "total_earnings",
            "earnings_by_bike",
            "verified_by",
            "verified_by_name",
            "verified_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "verified_by",
            "verified_at",
            "created_at",
            "updated_at",
        ]
    
    def get_total_earnings(self, obj):
        """Calculate total earnings across all owner's bikes"""
        return obj.calculate_total_earnings()
    
    def get_earnings_by_bike(self, obj):
        """Get earnings breakdown per bike"""
        return obj.get_earnings_by_bike()


class BikeOwnerWithBikesSerializer(BikeOwnerDetailSerializer):
    """
    Bike owner with full list of their bikes.
    Shows which driver is on which bike.
    """
    
    bikes = serializers.SerializerMethodField()
    
    class Meta(BikeOwnerDetailSerializer.Meta):
        fields = BikeOwnerDetailSerializer.Meta.fields + ["bikes"]
    
    def get_bikes(self, obj):
        """Return all bikes with driver assignments and earnings"""
        bikes_data = []
        for bike in obj.bikes.select_related('driver').all():
            bikes_data.append({
                "id": str(bike.id),
                "license_plate": bike.license_plate,
                "model": bike.model,
                "color": bike.color,
                "bike_type": bike.bike_type,
                "status": bike.status,
                "driver": {
                    "id": str(bike.driver.id),
                    "full_name": bike.driver.full_name,
                    "phone_number": bike.driver.phone_number,
                } if bike.driver else None,
                "assigned_at": bike.assigned_at,
                "total_earnings": bike.calculate_total_earnings(),
                "total_rides": bike.total_rides,
            })
        return bikes_data


# ══════════════════════════════════════════════════════════════════════════
# BIKE REGISTRATION SERIALIZERS
# ══════════════════════════════════════════════════════════════════════════

class BikeRegistrationSerializer(serializers.ModelSerializer):
    """For submitting bike + owner registration"""
    
    class Meta:
        model = BikeRegistration
        fields = [
            "id",
            "owner_name",
            "owner_phone",
            "owner_email",
            "owner_address",
            "bank_name",
            "account_number",
            "account_name",
            "id_document",
            "owner_photo",
            "bike_type",
            "license_plate",
            "model",
            "color",
            "year",
            "bike_photo",
            "registration_document",
            "additional_notes",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]
    
    def validate_license_plate(self, value):
        """Ensure plate doesn't already exist"""
        value = value.upper().strip()
        
        # Check existing bikes
        if Bike.objects.filter(license_plate=value).exists():
            raise serializers.ValidationError(
                "This license plate is already registered."
            )
        
        # Check pending registrations
        if BikeRegistration.objects.filter(
            license_plate=value,
            status="pending"
        ).exists():
            raise serializers.ValidationError(
                "This license plate is already pending approval."
            )
        
        return value
    
    def validate_owner_phone(self, value):
        """Format phone number"""
        return value.strip()
    
    def validate_owner_email(self, value):
        """Lowercase email"""
        return value.lower().strip()


class BikeRegistrationDetailSerializer(serializers.ModelSerializer):
    """Full registration details for admin review"""
    
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.full_name", read_only=True, allow_null=True
    )
    approved_owner_id = serializers.UUIDField(
        source="approved_owner.id", read_only=True, allow_null=True
    )
    approved_bike_id = serializers.UUIDField(
        source="approved_bike.id", read_only=True, allow_null=True
    )
    
    class Meta:
        model = BikeRegistration
        fields = [
            "id",
            "owner_name",
            "owner_phone",
            "owner_email",
            "owner_address",
            "bank_name",
            "account_number",
            "account_name",
            "id_document",
            "owner_photo",
            "bike_type",
            "license_plate",
            "model",
            "color",
            "year",
            "bike_photo",
            "registration_document",
            "additional_notes",
            "status",
            "reviewed_by",
            "reviewed_by_name",
            "reviewed_at",
            "rejection_reason",
            "approved_owner_id",
            "approved_bike_id",
            "created_at",
            "updated_at",
        ]


# ══════════════════════════════════════════════════════════════════════════
# UPDATED BIKE SERIALIZER (with owner info)
# ══════════════════════════════════════════════════════════════════════════
