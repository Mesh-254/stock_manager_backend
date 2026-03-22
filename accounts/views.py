from django.utils import timezone
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
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from accounts.permissions import CanManageShopUsers, IsSuperAdmin
from accounts.tasks import send_verification_email,  send_password_reset_email


logger = logging.getLogger(__name__)


class LoginView(APIView):
    """
    Authenticate user and return JWT access + refresh tokens
    """

    permission_classes = [AllowAny]

    def post(self, request):
        email_input = request.data.get("email", "").strip().lower()
        password = request.data.get("password")

        if not email_input:
            return Response({"detail": "Email is required."}, status=400)

        try:
            user = User.objects.get(email=email_input)
        except User.DoesNotExist:
            return Response({"detail": "Invalid credentials."}, status=401)

        if not user.is_active:
            return Response(
                {"detail": "Account not verified. Check your email."}, status=401
            )

        # If user has no password (Google signup), allow login without password
        if not user.has_usable_password():
            if password is not None:
                return Response(
                    {"detail": "This account uses Google login."}, status=400
                )
        else:
            if not password or not user.check_password(password):
                return Response({"detail": "Invalid credentials."}, status=401)

        # Generate JWT for SPA
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                    "shop_id": user.shop.id if user.shop else None,
                },
            }
        )


class LogoutView(APIView):
    """
    Blacklist refresh token to logout
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response({"detail": "Refresh token is required."}, status=400)

            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response({"detail": "Successfully logged out."}, status=205)
        except TokenError:
            return Response({"detail": "Invalid or expired refresh token."}, status=400)
        except Exception as e:
            logger.error(f"Logout error: {str(e)}")
            return Response({"detail": "Logout failed."}, status=500)


class RegisterView(APIView):
    """
    Register a new user account.
    - Creates inactive user
    - Sends verification email
    - Returns user data (not tokens — user must verify first)
    """

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
                role=validated_data.get("role", UserRole.SHOP_ADMIN),
                is_staff=True,  # Needed for admin access
            )

            # Generate and save verification token
            verification_token = str(uuid.uuid4())
            user.verification_token = verification_token
            user.is_active = False
            user.save(update_fields=["verification_token", "is_active"])

            # Auto-create shop for this new shop owner
            shop = Shop.objects.create(
                name=f"{user.full_name}'s Shop",  # or let them edit later
                owner=user,
                # add other defaults
            )
            user.shop = shop
            user.save()

            # Send verification email (pass the raw token — the task will build the full URL)
            send_verification_email.delay(user.email, verification_token)

            return Response(
                {
                    "message": "Registration successful. Please check your email to verify your account.",
                    "user": UserSerializer(user, context={"request": request}).data,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            logger.exception("Registration error")
            return Response(
                {
                    "detail": "An error occurred during registration.",
                    "error_type": "server_error",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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

class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"detail": "Email is required."}, status=400)

        email = email.lower().strip()
        user = User.objects.filter(email=email).first()

        if user:
            reset_token = str(uuid.uuid4())
            user.reset_token = reset_token
            user.reset_token_expires = timezone.now() + timedelta(hours=1)
            user.save(update_fields=["reset_token", "reset_token_expires"])

            reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password/{reset_token}"
            send_password_reset_email.delay(user.email, reset_url)

        # Always return same message to prevent email enumeration
        return Response({
            "message": "If an account with that email exists, a password reset link has been sent."
        }, status=200)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, token):
        password = request.data.get("password")
        if not password:
            return Response({"detail": "Password is required."}, status=400)

        try:
            user = User.objects.get(reset_token=token)
            
            if timezone.now() > user.reset_token_expires:
                return Response({"detail": "Reset link has expired."}, status=400)

            user.set_password(password)
            user.reset_token = None
            user.reset_token_expires = None
            user.save()

            return Response({"message": "Password reset successful."}, status=200)

        except User.DoesNotExist:
            return Response({"detail": "Invalid reset link."}, status=400)


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


# ==================== User ViewSet ====================


class UserViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing user instances.
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, CanManageShopUsers]


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
            return UserCreateSerializer
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
        send_verification_email.delay(user.email, verification_token)

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
