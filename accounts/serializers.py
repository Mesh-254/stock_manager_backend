from rest_framework import serializers
from django.contrib.auth import get_user_model
from accounts.models import UserRole
import re

User = get_user_model()


# =============================================================================
# User Serializer
# =============================================================================


class UserSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the User model using HyperlinkedModelSerializer.
    Includes role display, shop hyperlink, and related metadata.
    """

    # Show the human-readable role ("Admin", "Shop Manager")
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    # Nested hyperlink to related shop
    shop = serializers.HyperlinkedRelatedField(
        view_name="shop-detail",  # You’ll need to define this in your Shop viewset/router
        read_only=True,
    )

    class Meta:
        model = User
        fields = [
            "url",  # Hyperlinked identity field
            "id",
            "email",
            "full_name",
            "phone_number",
            "role",
            "role_display",
            "shop",
            "is_active",
            "is_staff",
            "created_at",
            "updated_at",
            "last_login",
        ]
        read_only_fields = [
            "id",
            "role_display",
            "shop",
            "is_active",
            "is_staff",
            "created_at",
            "updated_at",
            "last_login",
        ]
        extra_kwargs = {
            # ViewSet name to resolve hyperlinks
            "url": {"view_name": "user-detail"},
        }


# allows password on create only


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "email",
            "full_name",
            "phone_number",
            "password",
            "is_active",
        ]  # no role/shop - auto-set

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class RegisterSerializer(serializers.Serializer):
    """Enhanced serializer for user registration."""

    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=255)
    password = serializers.CharField(write_only=True, min_length=8)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=UserRole.choices, default=UserRole.SHOP_ADMIN
    )

    def validate_email(self, value):
        """Check if email is already in use."""
        email_lower = value.lower()
        if User.objects.filter(email=email_lower).exists():
            raise serializers.ValidationError("This email address is already in use.")
        return email_lower

    def validate_password(self, value):
        """Validate password strength."""
        if len(value) < 8:
            raise serializers.ValidationError(
                "Password must be at least 8 characters long."
            )

        if not any(c.isupper() for c in value):
            raise serializers.ValidationError(
                "Password must contain at least one uppercase letter."
            )

        if not any(c.islower() for c in value):
            raise serializers.ValidationError(
                "Password must contain at least one lowercase letter."
            )

        if not any(c.isdigit() for c in value):
            raise serializers.ValidationError(
                "Password must contain at least one number."
            )

        return value

    def validate_phone_number(self, value):
        if value and not re.match(
            r"^\+?[\d\s\-\(\)]+$", value
        ):  # ← removed $$$$, added () for common formats
            raise serializers.ValidationError("Please enter a valid phone number.")
        return value
