from django.shortcuts import redirect, render
from django.utils import timezone
from django.contrib import messages
from datetime import timedelta
from rest_framework import viewsets
from accounts.serializers import UserSerializer
from accounts.models import User
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from accounts.serializers import UserSerializer, RegisterSerializer
from accounts.models import User, UserRole
from shop_manager.models import Shop
import uuid
from rest_framework.decorators import api_view, permission_classes
import logging
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from accounts.permissions import CanManageShopUsers, IsSuperAdmin
from accounts.tasks import send_verification_email,  send_password_reset_email
from django.contrib.auth import login
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


logger = logging.getLogger(__name__)



def home_redirect_view(request):
    """Root URL (/) — redirect authenticated users to admin, others stay on frontend"""
    if request.user.is_authenticated:
        return redirect('admin:index')
    return redirect('account_login')


# =============================================================================
# LOGIN VIEW - PURE API FOR REACT
# =============================================================================
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        password = request.data.get("password")

        if not email:
            return Response({"detail": "Email is required."}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "Invalid credentials."}, status=401)

        if not user.is_active:
            return Response({"detail": "Account not verified. Check your email."}, status=401)

        if not user.check_password(password):
            return Response({"detail": "Invalid credentials."}, status=401)

        # Create JWT tokens
        refresh = RefreshToken.for_user(user)

        # Set Django session for Unfold admin
        user.backend = 'accounts.backends.CaseInsensitiveEmailBackend'
        login(request, user)   # This sets the session cookie

        # Dynamic redirect URL
        if user.role in [UserRole.SUPER_ADMIN, UserRole.SHOP_ADMIN] or user.is_staff:
            redirect_url = "/admin/"
        else:
            redirect_url = "/dashboard"

        return Response({
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "shop_id": user.shop.id if user.shop else None,
                "is_staff": user.is_staff,
            },
            "redirect_url": redirect_url
        }, status=200)


# =============================================================================
# LOGOUT
# =============================================================================
@method_decorator(csrf_exempt, name='dispatch')
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                RefreshToken(refresh_token).blacklist()
            return Response({"detail": "Successfully logged out."}, status=205)
        except Exception:
            return Response({"detail": "Logout failed."}, status=500)


# =============================================================================
# REGISTER - API ONLY
# =============================================================================
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data

        try:
            user = User.objects.create_user(
                email=validated_data["email"],
                full_name=validated_data["full_name"],
                password=validated_data["password"],
                phone_number=validated_data.get("phone_number"),
                role=validated_data.get("role", UserRole.SHOP_ADMIN)
            )

            verification_token = str(uuid.uuid4())
            user.verification_token = verification_token
            user.is_active = False
            user.is_staff = True
            user.save(update_fields=["verification_token", "is_active", "is_staff"])

            shop = Shop.objects.create(name=f"{user.full_name}'s Shop", owner=user)
            user.shop = shop
            user.save()

            verification_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email/{verification_token}"
            send_verification_email.delay(user.email, verification_url)

            return Response({
                "message": "Registration successful. Please check your email to verify your account.",
                "user": UserSerializer(user, context={"request": request}).data,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception("Registration error")
            return Response({"detail": "Server error during registration."}, status=500)

class VerifyEmailView(APIView):
    """
    Verify user email via token.
    GET /api/accounts/verify-email/<uuid:token>/
    """
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            # Find inactive user with matching token
            user = User.objects.get(
                verification_token=token,
                is_active=False
            )

            # Activate account
            user.is_active = True
            user.is_staff = True  # Allow access to admin if needed
            user.verification_token = None  # Clear token after use
            user.save(update_fields=['is_active', 'is_staff', 'verification_token'])

            logger.info(f"Email verified successfully for user: {user.email}")

            return Response(
                {
                    "message": "Email verified successfully!",
                    "detail": "Your account has been activated. You can now log in."
                },
                status=status.HTTP_200_OK
            )

        except User.DoesNotExist:
            logger.warning(f"Invalid or expired verification token attempted: {token}")
            return Response(
                {
                    "error": "Invalid or expired verification link.",
                    "detail": "This link may have already been used or has expired. Please request a new one."
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected error during email verification: {str(e)}")
            return Response(
                {"error": "An unexpected error occurred. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# =============================================================================
# PASSWORD RESET VIEWS (Production Ready)
# =============================================================================

class PasswordResetRequestView(APIView):
    """
    Senior Dev Implementation - Password Reset Request
    POST /accounts/password-reset/
    
    Features:
    - Case-insensitive email
    - Anti-enumeration protection (always returns same message)
    - Token is cryptographically secure UUID
    - Token expires in exactly 60 minutes (matches Celery email)
    - Fully async email via Celery
    - Proper logging
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()

        if not email:
            logger.warning("Password reset requested without email")
            return Response({"detail": "Email is required."}, status=400)

        # Find user (case-insensitive - matches your CaseInsensitiveEmailBackend)
        user = User.objects.filter(email=email).first()

        if user:
            # Generate secure token
            reset_token = str(uuid.uuid4())
            user.reset_token = reset_token
            user.reset_token_expires = timezone.now() + timedelta(hours=1)
            user.save(update_fields=["reset_token", "reset_token_expires"])

            # Build frontend reset URL using FRONTEND_URL from settings
            reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password/{reset_token}"

            # Send email asynchronously via Celery
            send_password_reset_email.delay(user.email, reset_url)

            logger.info(f"Password reset link generated and queued for {user.email}")
        else:
            # Security: do NOT reveal that email doesn't exist
            logger.info(f"Password reset attempted for non-existent email: {email}")

        # Always return the same message (prevents user enumeration attacks)
        return Response({
            "message": "If an account with that email exists, a password reset link has been sent."
        }, status=200)


class PasswordResetConfirmView(APIView):
    """
    Senior Dev Implementation - Set New Password
    POST /accounts/password-reset-confirm/<uuid:token>/
    
    Features:
    - Same password strength rules as RegisterSerializer
    - Token expiration check
    - Token is consumed (deleted) after successful use
    - Full error handling and logging
    - Returns user-friendly messages for frontend
    """
    permission_classes = [AllowAny]

    def post(self, request, token):
        password = request.data.get("password")

        if not password:
            return Response({"detail": "Password is required."}, status=400)

        try:
            # Find user by token
            user = User.objects.get(reset_token=token)

            # Check expiration
            if timezone.now() > user.reset_token_expires:
                logger.warning(f"Expired reset token used: {token}")
                return Response({"detail": "Reset link has expired. Please request a new one."}, status=400)

            # === Password Strength Validation (mirrors RegisterSerializer) ===
            if len(password) < 8:
                return Response({"detail": "Password must be at least 8 characters long."}, status=400)

            if not any(c.isupper() for c in password):
                return Response({"detail": "Password must contain at least one uppercase letter."}, status=400)

            if not any(c.islower() for c in password):
                return Response({"detail": "Password must contain at least one lowercase letter."}, status=400)

            if not any(c.isdigit() for c in password):
                return Response({"detail": "Password must contain at least one number."}, status=400)

            # Set new password (uses Django's secure hashing)
            user.set_password(password)

            # Consume the token (security best practice)
            user.reset_token = None
            user.reset_token_expires = None

            user.save(update_fields=["password", "reset_token", "reset_token_expires"])

            logger.info(f"Password successfully reset for user: {user.email}")

            return Response({
                "message": "Password has been reset successfully. You can now log in with your new password."
            }, status=200)

        except User.DoesNotExist:
            logger.warning(f"Invalid reset token attempted: {token}")
            return Response({"detail": "Invalid or expired reset link."}, status=400)

        except Exception as e:
            logger.error(f"Unexpected error during password reset: {str(e)}", exc_info=True)
            return Response({"detail": "An unexpected error occurred. Please try again."}, status=500)


class AdminPasswordResetView(APIView):  # Admin-only override
    permission_classes = [IsSuperAdmin]

    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            new_password = request.data.get("new_password")
            if not new_password:
                return Response({"detail": "New password required."}, status=400)
            user.set_password(new_password)
            user.save()
            # Optionally email user
            return Response({"message": f"Password reset for {user.email}."})
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)


@api_view(["POST"])
def check_email(request):
    email = request.data.get("email")
    if not email:
        return Response({"error": "Email is required"}, status=400)

    user = User.objects.filter(email=email).first()
    if not user:
        return Response({"exists": False, "is_active": False}, status=200)

    return Response({"exists": True, "is_active": user.is_active}, status=200)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return User.objects.all()
        elif self.request.user.role == UserRole.SHOP_ADMIN:
            return User.objects.filter(shop=self.request.user.shop)  # self + cashiers
        elif self.request.user.role == UserRole.CASHIER:
            return User.objects.filter(id=self.request.user.id)
        return User.objects.none()

    def get_serializer_class(self):
        if self.action == "create":
            return UserSerializer
        return UserSerializer

    def perform_create(self, serializer):
        if self.request.user.role == UserRole.SUPER_ADMIN:
            serializer.save()  # full flexibility
        elif self.request.user.role == UserRole.SHOP_ADMIN:
            serializer.save(
                shop=self.request.user.shop,
                role=UserRole.CASHIER,
                is_active=True,  # cashiers active immediately (admin-created)
            )
        else:
            raise PermissionDenied("You cannot create users.")

    def perform_update(self, serializer):
        # Prevent non-superadmins from changing role/shop
        if self.request.user.role != UserRole.SUPER_ADMIN:
            serializer.validated_data.pop("role", None)
            serializer.validated_data.pop("shop", None)
        serializer.save()


@api_view(["POST"])
@permission_classes([AllowAny])
def resend_confirmation_email(request):
    """Resend confirmation email for inactive accounts."""
    email = request.data.get("email")

    if not email:
        return Response(
            {"detail": "Email address is required.", "error_type": "email_required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email_lower = email.lower().strip()

    try:
        user = User.objects.get(email=email_lower)

        if user.is_active:
            return Response(
                {
                    "detail": "This account is already active. You can sign in normally.",
                    "error_type": "already_active",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate a new verification token (overwrite any old one)
        verification_token = str(uuid.uuid4())
        user.verification_token = verification_token
        user.save(update_fields=["verification_token"])


        # Queue the async email task
        verification_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email/{verification_token}"
        send_verification_email.delay(user.email, verification_url)

        logger.info(f"Resend verification email queued for {user.email}")

        return Response(
            {
                "message": "Confirmation email sent successfully. Please check your inbox.",
                "email_sent": True,
            },
            status=status.HTTP_200_OK,
        )

    except User.DoesNotExist:
        return Response(
            {
                "detail": "No account found with this email address.",
                "error_type": "user_not_found",
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        logger.error(f"Unexpected error in resend_confirmation_email: {str(e)}")
        return Response(
            {
                "detail": "An unexpected error occurred. Please try again later.",
                "error_type": "server_error",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
