import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from phonenumber_field.modelfields import PhoneNumberField

# =============================================================================
# ENUM: User Roles
# =============================================================================


class UserRole(models.TextChoices):
    """
    Enum for defining user roles in the system.
    Roles include Admin and Shop Manager, which determine access permissions.
    """
    SUPER_ADMIN = 'SuperAdmin', 'Super Admin'     # ← add this
    SHOP_ADMIN  = 'ShopAdmin',  'Shop Admin'      # ← rename for clarity
    CASHIER     = 'Cashier',    'Cashier'

# =============================================================================
# MANAGER: Custom User Manager
# =============================================================================


class CustomUserManager(BaseUserManager):
    """
    Custom manager for handling user creation, including user and superuser creation logic.
    """

    def create_user(self, email, full_name, password=None, **extra_fields):
        """
        Creates and returns a new user with the provided email and full name.
        Ensures password is set and email is normalized.
        """
        if not email:
            raise ValueError("The Email field is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        # Grant admin access based on role
        if extra_fields.get('role') in [UserRole.SUPER_ADMIN, UserRole.SHOP_ADMIN]:
            user.is_staff = True
            user.is_active = True

        user.save(using=self._db)
        return user
    
    
    def normalize_email(self, email):
        return email.lower().strip()

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        """
        Creates and returns a new superuser with admin privileges.
        Ensures superuser fields such as is_staff and is_superuser are set.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', UserRole.SUPER_ADMIN)

        if not password:
            raise ValueError("Superuser must have a password.")

        return self.create_user(email, full_name, password, **extra_fields)

# =============================================================================
# MODEL: Custom User
# =============================================================================


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for the system. Email is used as the unique identifier.
    This model supports multiple user roles, including Admin and Shop Manager.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    phone_number = PhoneNumberField(null=True, blank=True)
    role = models.CharField(
        max_length=20, choices=UserRole.choices, default=UserRole.SHOP_ADMIN)

    shop = models.ForeignKey(
        'shop_manager.Shop',  # Use string reference
        on_delete=models.SET_NULL,
        related_name='users', null=True, blank=True
    )

    #  Field for email verification token (UUID format)
    verification_token = models.CharField(max_length=36, null=True, blank=True)  # For UUID

    # Fields for password reset functionality
    reset_token = models.CharField(max_length=36, null=True, blank=True)
    reset_token_expires = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = CustomUserManager()

    def save(self, *args, **kwargs):
        """
        Overriding the save method to format email and full name before saving.
        """
        self.email = self.email.lower()
        self.full_name = self.full_name.title()
        super().save(*args, **kwargs)

    def __str__(self):
        """
        Returns a string representation of the user in the format:
        Full Name (email).
        """
        return f"{self.full_name} ({self.email})"

    class Meta:
        indexes = [
            models.Index(fields=["shop"]),
            models.Index(fields=["role"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["last_login"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["shop", "role"]),  # To filter users by both.
        ]
