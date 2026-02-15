from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """
    Limit login (OTP request) attempts to 10 per minute per IP.
    This prevents OTP spam and brute-force enumeration.
    """
    scope = "login"


class OTPVerifyRateThrottle(AnonRateThrottle):
    """
    Limit OTP verification attempts to 10 per minute per IP.
    Server-side OTP attempt counter provides a second layer of protection.
    """
    scope = "otp_verify"


class PasswordResetRateThrottle(AnonRateThrottle):
    """
    Limit password reset requests to 5 per minute per IP.
    """
    scope = "password_reset"