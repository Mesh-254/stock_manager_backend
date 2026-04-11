"""
Permissions for Shop Manager API & Admin

Central permission classes used by ViewSets, custom views, and admin.
Design decisions:
- Layered permissions (IsCashierOrHigher for read, IsShopAdmin for write).
- Object-level shop scoping via IsInSameShop (prevents cross-shop data leaks).
- Reused across DRF and Django admin for consistency.
"""

from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    """
    Only SuperAdmin users.
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "SuperAdmin"


class IsShopAdmin(permissions.BasePermission):
    """
    Only ShopAdmin users (full control within their shop).
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == "ShopAdmin"


class IsCashierOrHigher(permissions.BasePermission):
    """
    Cashier, ShopAdmin, or SuperAdmin.
    Cashiers have read-only access in most views.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ("SuperAdmin", "ShopAdmin", "Cashier")


class IsInSameShop(permissions.BasePermission):
    """
    Object-level permission: user can only access objects belonging to their own shop.
    SuperAdmin bypasses this check.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.role == "SuperAdmin":
            return True
        user_shop = getattr(request.user, "shop", None)
        if not user_shop:
            return False
        return getattr(obj, "shop", None) == user_shop
    

class IsInSameShopViaProduct(permissions.BasePermission):
    """
    Object-level permission for models that link to shop via product__shop
    (e.g. Stock, StockTransaction).
    """

    def has_object_permission(self, request, view, obj):
        if request.user.role == "SuperAdmin":
            return True

        user_shop = getattr(request.user, "shop", None)
        if not user_shop:
            return False

        # Try to get shop through common patterns
        if hasattr(obj, "product") and hasattr(obj.product, "shop"):
            return obj.product.shop == user_shop
        if hasattr(obj, "stock") and hasattr(obj.stock.product, "shop"):
            return obj.stock.product.shop == user_shop

        return False
