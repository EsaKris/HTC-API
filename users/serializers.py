from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


def normalize_phone(value: str) -> str:
    """
    Normalize Nigerian phone numbers to international format.
    08012345678   → +2348012345678
    2348012345678 → +2348012345678
    +2348012345678 → +2348012345678 (unchanged)
    """
    value = value.strip()
    if value.startswith('0'):
        return '+234' + value[1:]
    elif value.startswith('234') and not value.startswith('+'):
        return '+' + value
    elif not value.startswith('+'):
        raise serializers.ValidationError(
            "Phone number must start with 0 or country code e.g. +234..."
        )
    return value


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Register a new rider account."""

    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["id", "email", "phone_number", "full_name", "password"]
        read_only_fields = ["id"]

    def validate_phone_number(self, value):
        return normalize_phone(value)

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User.objects.create_user(
            phone_number=validated_data["phone_number"],
            email=validated_data["email"],
            full_name=validated_data["full_name"],
            password=password or None,
            role=User.Role.USER,
        )
        return user


class LoginRequestSerializer(serializers.Serializer):
    """Step 1 of login: provide phone number → OTP sent to email."""

    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        return normalize_phone(value)


class OTPVerifySerializer(serializers.Serializer):
    """Step 2 of login: provide OTP to get JWT tokens."""

    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_phone_number(self, value):
        return normalize_phone(value)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be numeric.")
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """Request a password-reset OTP by supplying registered email."""

    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    """Reset password using OTP delivered to email."""

    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    new_password = serializers.CharField(
        min_length=8, write_only=True, style={"input_type": "password"}
    )
    confirm_password = serializers.CharField(
        min_length=8, write_only=True, style={"input_type": "password"}
    )

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be numeric.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(attrs["new_password"])
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    """Read-only profile endpoint (/api/auth/me/)."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone_number",
            "full_name",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """Allows user to update their own full_name and email."""

    class Meta:
        model = User
        fields = ["full_name", "email"]

    def validate_email(self, value):
        user = self.context["request"].user
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value