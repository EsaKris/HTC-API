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
                 ↘ CANCELLED (by rider before assignment)
    """

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    FIXED_PRICE = 500  # ₦500 per trip — fixed platform rate

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

    # Pickup
    pickup_address = models.CharField(max_length=500)
    pickup_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    pickup_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    # Dropoff
    dropoff_address = models.CharField(max_length=500)
    dropoff_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    dropoff_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    price = models.PositiveIntegerField(default=FIXED_PRICE)

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )

    # Who cancelled and optional reason
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_rides",
    )
    cancellation_reason = models.TextField(blank=True)

    # Admin who assigned the driver
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rides_assigned",
    )

    # Lifecycle timestamps
    assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # Audit / notes
    rider_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rides"
        verbose_name = "Ride"
        verbose_name_plural = "Rides"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Ride #{str(self.id)[:8]} | {self.rider.full_name} → "
            f"{self.dropoff_address} [{self.status}]"
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