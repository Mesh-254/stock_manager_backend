# accounts/tasks.py
from __future__ import absolute_import, unicode_literals
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def send_verification_email(self, user_email: str, verification_token: str):
    verification_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email/{verification_token}"

    subject = "Activate Your SHOP Manager Account"
    message = (
        f"Hello,\n\n"
        f"Thank you for registering!\n\n"
        f"Please click the link below to verify your email and activate your account:\n\n"
        f"{verification_url}\n\n"
        f"This link will expire in 48 hours for security reasons.\n\n"
        f"If you didn't create an account, please ignore this email.\n\n"
        f"Thank you"
    )
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user_email]

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        logger.info(f"Verification email sent to {user_email}")
    except Exception as exc:
        logger.error(f"Failed to send verification email to {user_email}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def send_password_reset_email(self, user_email: str, reset_url: str):
    """
    Sends password reset email asynchronously.
    """
    subject = "Password Reset for SHOP Manager"
    message = (
        f"Hello,\n\n"
        f"You requested a password reset. Click the link below to set a new password:\n\n"
        f"Reset Link Expires in 60 minutes\n\n"
        f"{reset_url}\n\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"Thank you,\nShop Manager Team"
    )
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user_email]

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        logger.info(f"Password reset email sent to {user_email}")
    except Exception as exc:
        logger.error(f"Failed to send password reset email to {user_email}: {exc}")
        raise self.retry(exc=exc)
