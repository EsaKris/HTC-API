import random
import string
import logging
from datetime import timedelta

from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def generate_otp(length: int = 6) -> str:
    """Generate a secure numeric OTP."""
    return "".join(random.choices(string.digits, k=length))


def set_otp(user, purpose: str) -> str:
    """
    Attach a fresh OTP to the user and persist it.
    Returns the plain-text OTP (only safe moment to read it).
    """
    otp = generate_otp()
    user.otp_code = otp
    user.otp_expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    user.otp_purpose = purpose
    user.otp_attempts = 0
    user.save(
        update_fields=["otp_code", "otp_expires_at", "otp_purpose", "otp_attempts"]
    )
    return otp


def verify_otp(user, otp: str, purpose: str) -> tuple[bool, str]:
    """
    Validate an OTP against the stored one.
    Returns (success: bool, error_message: str).
    """
    if user.otp_attempts >= OTP_MAX_ATTEMPTS:
        return False, "Too many failed attempts. Please request a new OTP."

    if not user.otp_code or user.otp_purpose != purpose:
        return False, "No active OTP found for this action. Please request a new one."

    if not user.is_otp_valid:
        return False, "OTP has expired. Please request a new one."

    if user.otp_code != otp:
        user.increment_otp_attempts()
        remaining = OTP_MAX_ATTEMPTS - user.otp_attempts
        return False, f"Invalid OTP. {remaining} attempt(s) remaining."

    user.clear_otp()
    return True, ""


def send_otp_email(user, otp: str, purpose: str) -> bool:
    """
    Send OTP email. Returns True on success.
    """
    subject_map = {
        "login": "Your HFC Login OTP",
        "password_reset": "Your HFC Password Reset OTP",
    }
    subject = subject_map.get(purpose, "Your HFC OTP Code")

    context = {
        "full_name": user.full_name,
        "otp": otp,
        "expiry_minutes": OTP_EXPIRY_MINUTES,
        "purpose": purpose,
        "app_name": "Howfar Transport Company",
    }

    # HTML email body (inline fallback if templates not configured)
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
        <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; text-align: center;">
            <h1 style="color: #e94560; margin: 0;">HFC</h1>
            <p style="color: #aaa; font-size: 12px; margin-top: 4px;">Howfar Transport Company</p>
        </div>
        <div style="padding: 30px 20px;">
            <h2>Hi {user.full_name},</h2>
            <p>Your one-time passcode for <strong>{purpose.replace('_', ' ').title()}</strong> is:</p>
            <div style="background: #f0f4ff; border: 2px dashed #4a90e2; padding: 20px; text-align: center;
                        border-radius: 8px; margin: 20px 0;">
                <span style="font-size: 36px; font-weight: bold; letter-spacing: 10px; color: #1a1a2e;">
                    {otp}
                </span>
            </div>
            <p style="color: #888;">This code expires in <strong>{OTP_EXPIRY_MINUTES} minutes</strong>.</p>
            <p style="color: #888;">If you did not request this, please ignore this email or contact support.</p>
        </div>
        <hr style="border: 1px solid #eee;">
        <p style="color: #aaa; font-size: 12px; text-align: center;">
            &copy; 2025 Howfar Transport Company, Makurdi. All rights reserved.
        </p>
    </body>
    </html>
    """

    plain_text = (
        f"Hi {user.full_name},\n\n"
        f"Your HFC OTP for {purpose.replace('_', ' ')} is: {otp}\n\n"
        f"This code expires in {OTP_EXPIRY_MINUTES} minutes.\n\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"— Howfar Transport Company"
    )

    try:
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=False,
        )
        logger.info(f"OTP email sent to {user.email} for purpose={purpose}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send OTP email to {user.email}: {exc}", exc_info=True)
        return False


def send_driver_acceptance_email(user) -> bool:
    """Send acceptance + employment letter email to approved driver."""
    subject = "Congratulations! Your HFC Driver Application Has Been Approved"
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
        <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; text-align: center;">
            <h1 style="color: #e94560; margin: 0;">HFC</h1>
            <p style="color: #aaa; font-size: 12px;">Howfar Transport Company</p>
        </div>
        <div style="padding: 30px 20px;">
            <h2>Dear {user.full_name},</h2>
            <p>We are pleased to inform you that your application to become a driver
            with <strong>Howfar Transport Company (HFC)</strong> has been
            <span style="color: green;"><strong>APPROVED</strong></span>.</p>

            <h3 style="border-bottom: 2px solid #e94560; padding-bottom: 8px;">
                Employment Letter
            </h3>
            <p>This letter serves as official confirmation that you have been onboarded
            as a verified driver with HFC effective immediately.</p>
            <ul>
                <li>Your account has been activated on the HFC Driver App.</li>
                <li>A bike has been or will shortly be assigned to you.</li>
                <li>Trip fare: <strong>₦500 per ride</strong> (fixed rate).</li>
                <li>You are expected to maintain professional conduct at all times.</li>
            </ul>
            <p>Please log into the HFC Driver App using your registered phone number
            to start accepting rides.</p>
            <p>Welcome aboard!</p>
            <p><strong>HFC Management<br>Howfar Transport Company, Makurdi</strong></p>
        </div>
        <hr style="border: 1px solid #eee;">
        <p style="color: #aaa; font-size: 12px; text-align: center;">
            &copy; 2025 Howfar Transport Company. All rights reserved.
        </p>
    </body>
    </html>
    """
    plain_text = (
        f"Dear {user.full_name},\n\n"
        "Your driver application with Howfar Transport Company has been APPROVED.\n"
        "Please log in to the HFC Driver App to start accepting rides.\n\n"
        "Welcome aboard!\n— HFC Management"
    )
    try:
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error(f"Failed to send acceptance email to {user.email}: {exc}", exc_info=True)
        return False


def send_driver_rejection_email(user) -> bool:
    """Send rejection notification email to applicant."""
    subject = "Update on Your HFC Driver Application"
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
        <div style="background: #1a1a2e; padding: 20px; border-radius: 8px; text-align: center;">
            <h1 style="color: #e94560; margin: 0;">HFC</h1>
        </div>
        <div style="padding: 30px 20px;">
            <h2>Dear {user.full_name},</h2>
            <p>Thank you for your interest in joining <strong>Howfar Transport Company</strong>
            as a driver.</p>
            <p>After reviewing your application, we regret to inform you that we are
            <span style="color: red;"><strong>unable to proceed</strong></span> with your
            application at this time.</p>
            <p>This may be due to incomplete documentation or other internal criteria.
            You are welcome to re-apply in the future.</p>
            <p>We appreciate your interest and wish you the best.</p>
            <p><strong>HFC Management</strong></p>
        </div>
    </body>
    </html>
    """
    plain_text = (
        f"Dear {user.full_name},\n\n"
        "We regret to inform you that your HFC driver application was not approved at this time.\n"
        "You are welcome to re-apply in the future.\n\n"
        "— HFC Management"
    )
    try:
        send_mail(
            subject=subject,
            message=plain_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error(f"Failed to send rejection email to {user.email}: {exc}", exc_info=True)
        return False