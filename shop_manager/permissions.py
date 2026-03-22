from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "SuperAdmin"


class IsShopAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == "ShopAdmin"


class IsCashierOrHigher(permissions.BasePermission):
    """Cashier can read, ShopAdmin & SuperAdmin can read+write"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ("SuperAdmin", "ShopAdmin", "Cashier")


class IsInSameShop(permissions.BasePermission):
    """Object-level: only objects belonging to user's shop"""

    def has_object_permission(self, request, view, obj):
        if request.user.role == "SuperAdmin":
            return True
        user_shop = getattr(request.user, "shop", None)
        if not user_shop:
            return False
        return getattr(obj, "shop", None) == user_shop
