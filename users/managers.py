from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    """
    Manager for User model where phone_number is the unique identifier.
    """

    def create_user(self, phone_number, email, full_name, password=None, **extra_fields):
        if not phone_number:
            raise ValueError(_("Phone number is required."))
        if not email:
            raise ValueError(_("Email address is required."))

        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)

        user = self.model(
            phone_number=phone_number,
            email=email,
            full_name=full_name,
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, email, full_name, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self.create_user(phone_number, email, full_name, password, **extra_fields)