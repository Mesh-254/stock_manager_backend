from rest_framework.permissions import BasePermission
from .models import UserRole


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.SUPER_ADMIN
        )


class IsShopAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.SHOP_ADMIN
        )


class IsCashier(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.CASHIER
        )


class IsAdminOrSuperAdmin(BasePermission):  # For admin-only actions
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in (UserRole.SUPER_ADMIN, UserRole.SHOP_ADMIN)
        )


class CanManageShopUsers(BasePermission):
    """
    - Super Admin: full access
    - Shop Admin: can manage only users in their own shop (including create cashiers)
    - Cashier: can only view self
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        if request.user.role == UserRole.SUPER_ADMIN:
            return True

        if request.user.role == UserRole.SHOP_ADMIN:
            return True  # create allowed, others checked in object perm / queryset

        if request.user.role == UserRole.CASHIER:
            return view.action in [
                "retrieve",
                "update",
                "partial_update",
            ]  # only self via queryset

        return False

    def has_object_permission(self, request, view, obj):
        if request.user.role == UserRole.SUPER_ADMIN:
            return True

        if request.user.role == UserRole.SHOP_ADMIN:
            return obj.shop == request.user.shop

        if request.user.role == UserRole.CASHIER:
            return obj.id == request.user.id

        return False
