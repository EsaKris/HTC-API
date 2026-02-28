import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Ride(models.Model):
    """
    Core ride model for HFC platform.
    Fixed price of ₦500 per trip anywhere in Makurdi.

    Lifecycle:
        REQUESTED → ASSIGNED → IN_PROGRESS → COMPLETED
                 ↘ CANCELLED
    """

    # ================================
    # STATUS ENUM (Upgraded Version)
    # ================================
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    FIXED_PRICE = 500  # ₦500 fixed platform rate

    # ================================
    # PRIMARY IDENTIFICATION
    # ================================
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rider = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="rides_as_rider",
        limit_choices_to={"role": "user"},
    )

    driver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rides_as_driver",
        limit_choices_to={"role": "driver"},
    )

    # ================================
    # PICKUP LOCATION
    # ================================
    pickup_address = models.CharField(max_length=500)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ================================
    # DROPOFF LOCATION
    # ================================
    dropoff_address = models.CharField(max_length=500)
    dropoff_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ================================
    # REAL-TIME DRIVER LOCATION
    # ================================
    current_driver_lat = models.FloatField(null=True, blank=True)
    current_driver_lng = models.FloatField(null=True, blank=True)
    driver_location_updated_at = models.DateTimeField(null=True, blank=True)

    # ================================
    # ROUTE INFORMATION (OSRM)
    # ================================
    route_polyline = models.TextField(blank=True, help_text="Encoded polyline")
    route_geometry = models.JSONField(
        null=True,
        blank=True,
        help_text="Array of [lat, lng] coordinates"
    )
    estimated_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text="Duration in seconds"
    )
    estimated_distance = models.FloatField(
        null=True,
        blank=True,
        help_text="Distance in kilometers"
    )

    # ================================
    # TRIP SHARING
    # ================================
    share_token = models.CharField(max_length=32, unique=True, null=True, blank=True)
    share_enabled = models.BooleanField(default=False)

    # ================================
    # PRICING
    # ================================
    price = models.PositiveIntegerField(default=FIXED_PRICE)

    # ================================
    # STATUS
    # ================================
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )

    # ================================
    # ASSIGNMENT & CANCELLATION
    # ================================
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rides_assigned",
    )

    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_rides",
    )
    cancellation_reason = models.TextField(blank=True)

    # ================================
    # LIFECYCLE TIMESTAMPS
    # ================================
    assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # ================================
    # AUDIT
    # ================================
    rider_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ================================
    # META CONFIG
    # ================================
    class Meta:
        db_table = "rides"
        verbose_name = "Ride"
        verbose_name_plural = "Rides"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Ride #{str(self.id)[:8]} | "
            f"{self.rider.full_name} → {self.dropoff_address} "
            f"[{self.status}]"
        )


class RideStatusLog(models.Model):
    """
    Audit trail: every status change is recorded here.
    Satisfies the 'audit logs for ride assignment and status updates' requirement.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name="status_logs")

    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15)

    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    note = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ride_status_logs"
        ordering = ["timestamp"]

    def __str__(self):
        return f"Ride {str(self.ride_id)[:8]}: {self.from_status} → {self.to_status}"

class DriverLocation(models.Model):
    """Stores current location of each driver for fleet tracking"""
    driver = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='current_location',
        limit_choices_to={'role': 'driver'}
    )
    latitude = models.FloatField()
    longitude = models.FloatField()
    heading = models.FloatField(null=True, blank=True, help_text="Direction in degrees (0-360)")
    speed = models.FloatField(null=True, blank=True, help_text="Speed in km/h")
    accuracy = models.FloatField(null=True, blank=True, help_text="GPS accuracy in meters")
    is_active = models.BooleanField(default=True, help_text="Is driver currently available")
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'driver_locations'
        verbose_name = 'Driver Location'
        verbose_name_plural = 'Driver Locations'
    
    def __str__(self):
        return f"{self.driver.full_name} - ({self.latitude}, {self.longitude})"
