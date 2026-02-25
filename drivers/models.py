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

class BikeOwner(models.Model):
    """
    A person who owns bikes and rents them out through the platform.
    Bike owners are NOT drivers - they just provide bikes for drivers to use.
    They earn money based on rides completed with their bikes.
    """
    
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Verification"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        INACTIVE = "inactive", "Inactive"
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Personal Information
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(unique=True)
    address = models.TextField(blank=True, help_text="Physical address for contact")
    
    # Bank/Payment Information (for earnings payout)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    account_name = models.CharField(max_length=255, blank=True)
    
    # Identity Verification
    id_document = models.FileField(
        upload_to="bike_owners/documents/",
        null=True,
        blank=True,
        help_text="National ID, Driver's License, or Passport"
    )
    profile_photo = models.ImageField(
        upload_to="bike_owners/photos/",
        null=True,
        blank=True,
    )
    
    # Status
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    
    # Notes from admin
    admin_notes = models.TextField(
        blank=True,
        help_text="Internal notes about this bike owner"
    )
    
    # Revenue tracking (computed field - will be calculated from rides)
    # We'll add methods to calculate this
    
    # Admin who verified
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_bike_owners",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "bike_owners"
        verbose_name = "Bike Owner"
        verbose_name_plural = "Bike Owners"
        ordering = ["-created_at"]
    
    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"
    
    @property
    def total_bikes(self):
        """Number of bikes owned"""
        return self.bikes.count()
    
    @property
    def active_bikes(self):
        """Number of bikes currently in use"""
        return self.bikes.filter(status=Bike.BikeStatus.IN_USE).count()
    
    def calculate_total_earnings(self):
        """
        Calculate total earnings from all bikes owned.
        This sums up all completed rides using this owner's bikes.
        """
        from rides.models import Ride  # Import here to avoid circular import
        
        total = Ride.objects.filter(
            driver__assigned_bike__owner=self,
            status="COMPLETED"
        ).aggregate(total=models.Sum('price'))['total'] or 0
        
        return total
    
    def get_earnings_by_bike(self):
        """
        Returns a dict of {bike_id: total_earnings} for all owner's bikes.
        """
        from rides.models import Ride
        
        earnings = {}
        for bike in self.bikes.all():
            total = Ride.objects.filter(
                driver__assigned_bike=bike,
                status="COMPLETED"
            ).aggregate(total=models.Sum('price'))['total'] or 0
            earnings[str(bike.id)] = total
        
        return earnings


# ═══════════════════════════════════════════════════════════════════════════
# UPDATED BIKE MODEL - REPLACE YOUR EXISTING Bike MODEL WITH THIS
# ═══════════════════════════════════════════════════════════════════════════

class Bike(models.Model):
    """
    A bike provided by a BikeOwner and assigned to a Driver.
    Tracks earnings for revenue sharing with the owner.
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

    # THE OWNER (person who owns the bike - may NOT be a driver)
    owner = models.ForeignKey(
        BikeOwner,
        on_delete=models.CASCADE,
        related_name="bikes",
        help_text="The person who owns this bike"
    )

    # THE DRIVER (assigned by admin - person who actually drives)
    driver = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_bike",
        limit_choices_to={"role": "driver"},
        help_text="The driver currently assigned to use this bike"
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

    # Photos (for admin verification)
    bike_photo = models.ImageField(
        upload_to="bikes/photos/",
        null=True,
        blank=True,
    )
    registration_document = models.FileField(
        upload_to="bikes/documents/",
        null=True,
        blank=True,
    )

    # Admin tracking
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bikes_assigned",
        help_text="Admin who assigned this bike to the driver"
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
        return f"{self.license_plate} (Owner: {self.owner.full_name}) → Driver: {driver_name}"
    
    def calculate_total_earnings(self):
        """
        Calculate total earnings for this specific bike.
        Used to pay the owner.
        """
        from rides.models import Ride
        
        total = Ride.objects.filter(
            driver__assigned_bike=self,
            status="COMPLETED"
        ).aggregate(total=models.Sum('price'))['total'] or 0
        
        return total
    
    @property
    def total_rides(self):
        """Count of completed rides for this bike"""
        from rides.models import Ride
        return Ride.objects.filter(
            driver__assigned_bike=self,
            status="COMPLETED"
        ).count()


# ═══════════════════════════════════════════════════════════════════════════
# BIKE REGISTRATION MODEL - UPDATED FOR OWNER-BASED REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════

class BikeRegistration(models.Model):
    """
    A bike owner submits this to register their bike on the platform.
    Admin reviews and approves/rejects.
    Once approved, a Bike record is created.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Owner information (can be new person or existing BikeOwner)
    owner_name = models.CharField(max_length=255)
    owner_phone = models.CharField(max_length=20)
    owner_email = models.EmailField()
    owner_address = models.TextField(blank=True)
    
    # Bank details for payments
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    account_name = models.CharField(max_length=255, blank=True)

    # Identity verification
    id_document = models.FileField(
        upload_to="registrations/owner_documents/",
        null=True,
        blank=True,
    )
    owner_photo = models.ImageField(
        upload_to="registrations/owner_photos/",
        null=True,
        blank=True,
    )

    # Bike details
    bike_type = models.CharField(max_length=20, choices=Bike.BikeType.choices)
    license_plate = models.CharField(max_length=20)
    model = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=50, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)

    # Bike documents
    bike_photo = models.ImageField(
        upload_to="registrations/bike_photos/",
        null=True,
        blank=True,
    )
    registration_document = models.FileField(
        upload_to="registrations/bike_documents/",
        null=True,
        blank=True,
    )

    additional_notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Admin review
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_bike_registrations",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Links to created records (once approved)
    approved_owner = models.ForeignKey(
        BikeOwner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registrations",
    )
    approved_bike = models.OneToOneField(
        Bike,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registration",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bike_registrations"
        verbose_name = "Bike Registration"
        verbose_name_plural = "Bike Registrations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.license_plate} by {self.owner_name} — {self.status}"


