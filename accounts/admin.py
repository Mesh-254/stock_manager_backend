# accounts/admin.py (fixed)

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin
from .models import User, UserRole


@admin.register(User)
class UserAdmin(ModelAdmin, BaseUserAdmin):
    # Explicitly override ordering to avoid inheriting 'username' from BaseUserAdmin
    ordering = ("email",)  # or ("-created_at", "email") or any valid fields

    list_display = ("email", "full_name", "role", "shop", "is_active", "created_at")
    search_fields = ("email", "full_name")
    list_filter = ("role", "is_active", "shop")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "phone_number", "role", "shop")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "full_name",
                    "password1",
                    "password2",
                    "role",
                    "shop",
                ),
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == UserRole.SUPER_ADMIN:  # Better: use the enum value
            return qs
        elif request.user.role == UserRole.SHOP_ADMIN:
            return qs.filter(shop=request.user.shop)
        return qs.none()
    
    # Allow ShopAdmin to view/change users in their shop
    def has_view_permission(self, request, obj=None):
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        if request.user.role == UserRole.SHOP_ADMIN:
            return obj is None or obj.shop == request.user.shop
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return request.user.role in [UserRole.SUPER_ADMIN, UserRole.SHOP_ADMIN]