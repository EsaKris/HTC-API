import logging

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from core.throttles import LoginRateThrottle, OTPVerifyRateThrottle, PasswordResetRateThrottle
from core.utils import (
    set_otp,
    verify_otp,
    send_otp_email,
    send_driver_acceptance_email,  # noqa – exported from here for convenience
)
from .serializers import (
    UserRegistrationSerializer,
    LoginRequestSerializer,
    OTPVerifySerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _get_tokens_for_user(user):
    """Return access + refresh JWT token pair for a user."""
    refresh = RefreshToken.for_user(user)
    # Embed role in token payload for frontend convenience
    refresh["role"] = user.role
    refresh["full_name"] = user.full_name
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class RegisterView(APIView):
    """
    POST /api/auth/register/
    Create a new rider account.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            {
                "message": "Account created successfully. Please log in via your phone number.",
                "user": {
                    "id": str(user.id),
                    "full_name": user.full_name,
                    "email": user.email,
                    "phone_number": user.phone_number,
                    "role": user.role,
                },
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Login (Step 1) — Request OTP
# ---------------------------------------------------------------------------

class LoginRequestOTPView(APIView):
    """
    POST /api/auth/login/
    Accepts phone_number → looks up user → sends OTP to their email.

    To prevent user enumeration, we always return a generic success
    response even if the phone number doesn't exist.
    """

    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data["phone_number"]

        try:
            user = User.objects.get(phone_number=phone_number, is_active=True)
        except User.DoesNotExist:
            # Return the same generic response to avoid user enumeration
            return Response(
                {"message": "If this phone number is registered, an OTP has been sent to the associated email."},
                status=status.HTTP_200_OK,
            )

        otp = set_otp(user, purpose=User.OTPPurpose.LOGIN)
        email_sent = send_otp_email(user, otp, purpose=User.OTPPurpose.LOGIN)

        if not email_sent:
            logger.error(f"OTP email failed for user {user.id}")
            return Response(
                {"detail": "Failed to send OTP. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Mask email for display: j***@gmail.com
        masked_email = _mask_email(user.email)
        return Response(
            {
                "message": f"OTP sent to {masked_email}. Valid for 10 minutes.",
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Login (Step 2) — Verify OTP → JWT
# ---------------------------------------------------------------------------

class VerifyOTPView(APIView):
    """
    POST /api/auth/verify-otp/
    Accepts phone_number + otp → returns JWT access & refresh tokens.
    """

    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyRateThrottle]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data["phone_number"]
        otp = serializer.validated_data["otp"]

        try:
            user = User.objects.get(phone_number=phone_number, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        success, error_msg = verify_otp(user, otp, purpose=User.OTPPurpose.LOGIN)
        if not success:
            return Response(
                {"detail": error_msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tokens = _get_tokens_for_user(user)
        return Response(
            {
                "message": "Login successful.",
                "tokens": tokens,
                "user": {
                    "id": str(user.id),
                    "full_name": user.full_name,
                    "email": user.email,
                    "phone_number": user.phone_number,
                    "role": user.role,
                },
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------

class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    Request a password-reset OTP sent to registered email.
    """

    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            # Generic response to prevent enumeration
            return Response(
                {"message": "If this email is registered, a reset OTP has been sent."},
                status=status.HTTP_200_OK,
            )

        otp = set_otp(user, purpose=User.OTPPurpose.PASSWORD_RESET)
        email_sent = send_otp_email(user, otp, purpose=User.OTPPurpose.PASSWORD_RESET)

        if not email_sent:
            return Response(
                {"detail": "Failed to send OTP. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {"message": "If this email is registered, a reset OTP has been sent."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Reset Password
# ---------------------------------------------------------------------------

class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    Verify OTP and set a new password.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        new_password = serializer.validated_data["new_password"]

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invalid request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        success, error_msg = verify_otp(user, otp, purpose=User.OTPPurpose.PASSWORD_RESET)
        if not success:
            return Response(
                {"detail": error_msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {"message": "Password reset successfully. You can now log in."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Blacklist the provided refresh token (requires JWT blacklist app).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"message": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class MeView(APIView):
    """
    GET  /api/auth/me/  → return authenticated user's profile
    PATCH /api/auth/me/ → update full_name / email
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserProfileSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_email(email: str) -> str:
    """Turn john.doe@gmail.com into j***@gmail.com."""
    try:
        local, domain = email.split("@")
        return f"{local[0]}***@{domain}"
    except Exception:
        return "***"