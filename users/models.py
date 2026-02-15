import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from .managers import CustomUserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for HFC platform.
    Login is via phone number; OTP is delivered to registered email.
    """

    class Role(models.TextChoices):
        USER = "user", "Rider"
        DRIVER = "driver", "Driver"
        PENDING_DRIVER = "pending_driver", "Pending Driver"
        ADMIN = "admin", "Admin"

    class OTPPurpose(models.TextChoices):
        LOGIN = "login", "Login"
        PASSWORD_RESET = "password_reset", "Password Reset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.USER, db_index=True
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # OTP fields
    otp_code = models.CharField(max_length=6, null=True, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_purpose = models.CharField(
        max_length=20,
        choices=OTPPurpose.choices,
        null=True,
        blank=True,
    )
    otp_attempts = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["email", "full_name"]

    objects = CustomUserManager()

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"

    @property
    def is_otp_valid(self):
        """Check if OTP is not expired."""
        if not self.otp_expires_at:
            return False
        return timezone.now() < self.otp_expires_at

    def clear_otp(self):
        """Clear OTP data after successful use."""
        self.otp_code = None
        self.otp_expires_at = None
        self.otp_purpose = None
        self.otp_attempts = 0
        self.save(update_fields=["otp_code", "otp_expires_at", "otp_purpose", "otp_attempts"])

    def increment_otp_attempts(self):
        """Track OTP attempts for brute-force protection."""
        self.otp_attempts += 1
        self.save(update_fields=["otp_attempts"])