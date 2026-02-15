from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import DriverApplication, Bike

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

    driver_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Bike
        fields = [
            "id",
            "driver",
            "driver_name",
            "bike_type",
            "license_plate",
            "model",
            "color",
            "year",
            "status",
            "assigned_by",
            "assigned_by_name",
            "assigned_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "assigned_by", "assigned_by_name", "assigned_at", "created_at", "updated_at"]

    def get_driver_name(self, obj):
        return obj.driver.full_name if obj.driver else None

    def get_assigned_by_name(self, obj):
        return obj.assigned_by.full_name if obj.assigned_by else None


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