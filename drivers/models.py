import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class DriverApplication(models.Model):
    """
    Submitted by a user who wants to become a driver.
    Admin reviews and approves or rejects.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The applicant must already have a user account
    applicant = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="driver_application",
        limit_choices_to={"role__in": ["user", "pending_driver"]},
    )

    # Optional supporting document (resume, ID scan, etc.)
    resume = models.FileField(
        upload_to="driver_applications/resumes/",
        null=True,
        blank=True,
    )

    # Applicant-supplied details
    guarantor_name = models.CharField(max_length=255, blank=True)
    guarantor_phone = models.CharField(max_length=20, blank=True)
    years_of_experience = models.PositiveSmallIntegerField(default=0)
    additional_notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Admin who reviewed the application
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "driver_applications"
        verbose_name = "Driver Application"
        verbose_name_plural = "Driver Applications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.applicant.full_name} — {self.status}"


class Bike(models.Model):
    """
    Represents a bike assigned to an approved driver.
    One driver can have one active bike at a time.
    """

    class BikeType(models.TextChoices):
        STANDARD = "standard", "Standard Bike"
        SPORT = "sport", "Sport Bike"
        CARGO = "cargo", "Cargo Bike"

    class BikeStatus(models.TextChoices):
        AVAILABLE = "available", "Available"
        IN_USE = "in_use", "In Use"
        MAINTENANCE = "maintenance", "Under Maintenance"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    driver = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_bike",
        limit_choices_to={"role": "driver"},
    )

    bike_type = models.CharField(
        max_length=20, choices=BikeType.choices, default=BikeType.STANDARD
    )
    license_plate = models.CharField(max_length=20, unique=True)
    model = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=50, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=15,
        choices=BikeStatus.choices,
        default=BikeStatus.AVAILABLE,
        db_index=True,
    )

    # Admin who assigned the bike
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bikes_assigned",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bikes"
        verbose_name = "Bike"
        verbose_name_plural = "Bikes"
        ordering = ["-created_at"]

    def __str__(self):
        driver_name = self.driver.full_name if self.driver else "Unassigned"
        return f"{self.license_plate} ({self.bike_type}) → {driver_name}"