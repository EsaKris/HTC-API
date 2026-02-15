from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Ride, RideStatusLog

User = get_user_model()


# ---------------------------------------------------------------------------
# Nested helpers
# ---------------------------------------------------------------------------

class RiderSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "phone_number"]


class DriverSummarySerializer(serializers.ModelSerializer):
    bike_plate = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "phone_number", "bike_plate"]

    def get_bike_plate(self, obj):
        bike = getattr(obj, "assigned_bike", None)
        return bike.license_plate if bike else None


class RideStatusLogSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RideStatusLog
        fields = ["id", "from_status", "to_status", "changed_by_name", "note", "timestamp"]

    def get_changed_by_name(self, obj):
        return obj.changed_by.full_name if obj.changed_by else "System"


# ---------------------------------------------------------------------------
# Ride read serializer (used everywhere for consistent responses)
# ---------------------------------------------------------------------------

class RideSerializer(serializers.ModelSerializer):
    rider = RiderSummarySerializer(read_only=True)
    driver = DriverSummarySerializer(read_only=True)
    status_logs = RideStatusLogSerializer(many=True, read_only=True)
    price_display = serializers.SerializerMethodField()

    class Meta:
        model = Ride
        fields = [
            "id",
            "rider",
            "driver",
            "pickup_address",
            "pickup_lat",
            "pickup_lng",
            "dropoff_address",
            "dropoff_lat",
            "dropoff_lng",
            "price",
            "price_display",
            "status",
            "rider_notes",
            "cancellation_reason",
            "assigned_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            "status_logs",
        ]

    def get_price_display(self, obj):
        return f"₦{obj.price:,}"


# ---------------------------------------------------------------------------
# Rider: Request a ride
# ---------------------------------------------------------------------------

class RideRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ride
        fields = [
            "id",
            "pickup_address",
            "pickup_lat",
            "pickup_lng",
            "dropoff_address",
            "dropoff_lat",
            "dropoff_lng",
            "rider_notes",
            "price",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "price", "status", "created_at"]

    def validate(self, attrs):
        rider = self.context["request"].user

        # Prevent multiple active rides
        active_statuses = [Ride.Status.REQUESTED, Ride.Status.ASSIGNED, Ride.Status.IN_PROGRESS]
        if Ride.objects.filter(rider=rider, status__in=active_statuses).exists():
            raise serializers.ValidationError(
                "You already have an active ride. Complete or cancel it before requesting a new one."
            )

        # Pickup and dropoff must be different
        if attrs.get("pickup_address", "").strip().lower() == attrs.get("dropoff_address", "").strip().lower():
            raise serializers.ValidationError(
                "Pickup and dropoff locations cannot be the same."
            )
        return attrs

    def create(self, validated_data):
        return Ride.objects.create(
            rider=self.context["request"].user,
            price=Ride.FIXED_PRICE,
            **validated_data,
        )


# ---------------------------------------------------------------------------
# Rider: Cancel ride
# ---------------------------------------------------------------------------

class RideCancelSerializer(serializers.Serializer):
    cancellation_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=300,
        help_text="Optional reason for cancellation.",
    )


# ---------------------------------------------------------------------------
# Admin: Assign driver to ride
# ---------------------------------------------------------------------------

class RideAssignSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField(help_text="UUID of the approved driver to assign.")

    def validate_driver_id(self, value):
        try:
            driver = User.objects.get(id=value, role=User.Role.DRIVER, is_active=True)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "Driver not found or not an active approved driver."
            )

        # Ensure driver isn't already on an active ride
        active = Ride.objects.filter(
            driver=driver,
            status__in=[Ride.Status.ASSIGNED, Ride.Status.IN_PROGRESS],
        ).exists()
        if active:
            raise serializers.ValidationError(
                f"Driver '{driver.full_name}' already has an active ride in progress."
            )
        return value


# ---------------------------------------------------------------------------
# Driver: Update ride status
# ---------------------------------------------------------------------------

class RideStatusUpdateSerializer(serializers.Serializer):
    """
    Driver can only advance status in the allowed direction:
      ASSIGNED → IN_PROGRESS → COMPLETED
    """

    ALLOWED_TRANSITIONS = {
        Ride.Status.ASSIGNED: Ride.Status.IN_PROGRESS,
        Ride.Status.IN_PROGRESS: Ride.Status.COMPLETED,
    }

    status = serializers.ChoiceField(
        choices=[Ride.Status.IN_PROGRESS, Ride.Status.COMPLETED]
    )

    def validate(self, attrs):
        ride = self.context["ride"]
        new_status = attrs["status"]
        expected_next = self.ALLOWED_TRANSITIONS.get(ride.status)

        if expected_next is None:
            raise serializers.ValidationError(
                f"Ride in status '{ride.status}' cannot be updated by the driver."
            )
        if new_status != expected_next:
            raise serializers.ValidationError(
                f"Invalid transition. Current status is '{ride.status}'. "
                f"Next allowed status is '{expected_next}'."
            )
        return attrs


# ---------------------------------------------------------------------------
# Admin: Analytics summary
# ---------------------------------------------------------------------------

class RideAnalyticsSerializer(serializers.Serializer):
    total_rides = serializers.IntegerField()
    total_completed = serializers.IntegerField()
    total_cancelled = serializers.IntegerField()
    total_in_progress = serializers.IntegerField()
    total_requested = serializers.IntegerField()
    total_earnings = serializers.SerializerMethodField()
    total_drivers = serializers.IntegerField()
    total_riders = serializers.IntegerField()

    def get_total_earnings(self, obj):
        value = obj.get("total_earnings", 0)
        return f"₦{value:,}"