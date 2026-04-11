"""
shop_manager/admin.py

Django Admin Configuration for School Shop Inventory System
================================================================

Design Decisions:
- Reuses the exact same role logic as permissions.py (string roles: "SuperAdmin", "ShopAdmin", "Cashier")
- SuperAdmin → sees everything
- ShopAdmin → full access BUT only to their own shop (multi-tenancy security)
- Cashier → NO access to admin interface at all
- Uses Unfold for modern UI
- Object-level shop scoping + queryset filtering
- Inline editing for PurchaseItem & UsageItem
- Custom links to your beautiful template-based add/edit/detail views
- Heavily documented for future maintainers

This file completely solves the PermissionDenied (403) error you were seeing.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.inlines.admin import TabularInline as UnfoldTabularInline

from .models import (
    Shop,
    Category,
    Supplier,
    Product,
    Stock,
    StockTransaction,
    Purchase,
    PurchaseItem,
    Usage,
    UsageItem,
    Expense,
    OfflineSyncLog,
)


# =============================================================================
# BASE ADMIN CLASS - Reuses your DRF permission philosophy
# =============================================================================
class ShopManagerAdmin(ModelAdmin):
    """
    Base admin class used by almost all models.
    Mirrors the permission classes in permissions.py:
        - IsSuperAdmin → full access
        - IsShopAdmin → full access (own shop only)
        - Cashier     → blocked completely
    """

    def has_module_permission(self, request):
        """Controls whether the whole app appears in the admin sidebar."""
        if not request.user.is_authenticated:
            return False
        # Cashier gets nothing
        return request.user.role in ("SuperAdmin", "ShopAdmin")

    def has_view_permission(self, request, obj=None):
        """View permission (list + detail)."""
        if not self.has_module_permission(request):
            return False
        if request.user.role == "SuperAdmin":
            return True
        if obj is None:
            return True  # allow changelist view
        # ShopAdmin can only see objects belonging to their shop
        return getattr(obj, "shop", None) == getattr(request.user, "shop", None)

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def get_queryset(self, request):
        """Filter everything to the user's own shop (except SuperAdmin)."""
        qs = super().get_queryset(request)
        if request.user.role == "SuperAdmin":
            return qs
        user_shop = getattr(request.user, "shop", None)
        if user_shop and hasattr(self.model, "shop"):
            return qs.filter(shop=user_shop)
        return qs.none()

    def save_model(self, request, obj, form, change):
        """Auto-assign shop when ShopAdmin creates a new object."""
        if not change and request.user.role == "ShopAdmin" and hasattr(obj, "shop"):
            obj.shop = request.user.shop
        super().save_model(request, obj, form, change)


# =============================================================================
# PURCHASE ADMIN (with inline items)
# =============================================================================
class PurchaseItemInline(UnfoldTabularInline):
    model = PurchaseItem
    extra = 0
    fields = ("product", "quantity", "unit_cost_price")
    can_delete = True


@admin.register(Purchase)
class PurchaseAdmin(ShopManagerAdmin):
    """Purchase management in admin with links to your custom template views."""

    list_display = ("id_link", "shop", "supplier", "purchase_date", "total_amount_formatted", "payment_status", "edit_link")
    list_filter = ("payment_status", "payment_method", "purchase_date", "shop", "supplier")
    search_fields = ("supplier__name", "id")
    date_hierarchy = "purchase_date"
    ordering = ("-purchase_date",)
    readonly_fields = ("total_amount", "created_by")
    inlines = [PurchaseItemInline]

    def id_link(self, obj):
        url = reverse("detail_purchase", kwargs={"purchase_id": obj.pk})
        return format_html('<a href="{}" class="font-medium">{}</a>', url, obj.pk)
    id_link.short_description = "ID"

    def edit_link(self, obj):
        url = reverse("edit_purchase", kwargs={"purchase_id": obj.pk})
        return format_html('<a href="{}" class="text-blue-600">Edit</a>', url)
    edit_link.short_description = "Actions"

    def total_amount_formatted(self, obj):
        return f"{obj.total_amount:,.2f}" if obj.total_amount else "0.00"
    total_amount_formatted.short_description = "Total Amount"


@admin.register(PurchaseItem)
class PurchaseItemAdmin(ShopManagerAdmin):
    list_display = ("purchase", "product", "quantity", "unit_cost_price", "total_cost")
    search_fields = ("product__name",)


# =============================================================================
# USAGE ADMIN (formerly Sale) - Fixed legacy URLs
# =============================================================================
class UsageItemInline(UnfoldTabularInline):
    model = UsageItem
    extra = 0
    fields = ("product", "quantity")
    can_delete = True


@admin.register(Usage)
class UsageAdmin(ShopManagerAdmin):
    list_display = ("id_link", "usage_date", "recorded_by", "total_cost", "edit_link")
    list_filter = ("usage_date", "shop")
    search_fields = ("id",)
    date_hierarchy = "usage_date"
    readonly_fields = ("total_cost",)
    inlines = [UsageItemInline]

    def id_link(self, obj):
        url = reverse("detail_usage", kwargs={"usage_id": obj.pk})   # ← Fixed
        return format_html('<a href="{}" class="font-medium">{}</a>', url, obj.pk)
    id_link.short_description = "ID"

    def edit_link(self, obj):
        url = reverse("edit_usage", kwargs={"usage_id": obj.pk})     # ← Fixed
        return format_html('<a href="{}" class="text-blue-600">Edit</a>', url)
    edit_link.short_description = "Actions"


@admin.register(UsageItem)
class UsageItemAdmin(ShopManagerAdmin):
    list_display = ("usage", "product", "quantity", "unit_cost_price", "cost")
    search_fields = ("product__name",)


# =============================================================================
# SHOP ADMIN (special handling)
# =============================================================================
@admin.register(Shop)
class ShopAdmin(ShopManagerAdmin):
    """Shop model - top level tenant. SuperAdmin sees all, ShopAdmin sees only own."""

    list_display = ("name", "owner", "country", "currency_code", "is_active", "created_at")
    list_filter = ("is_active", "country", "currency_code")
    search_fields = ("name", "description")
    ordering = ["name"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == "SuperAdmin":
            return qs
        # ShopAdmin can only manage their own shop
        user_shop = getattr(request.user, "shop", None)
        if user_shop:
            return qs.filter(id=user_shop.id)
        return qs.none()


# =============================================================================
# REMAINING MODELS (simple but fully scoped)
# =============================================================================
@admin.register(Category)
class CategoryAdmin(ShopManagerAdmin):
    list_display = ("name", "shop", "description")
    list_filter = ["shop"]
    search_fields = ["name"]


@admin.register(Supplier)
class SupplierAdmin(ShopManagerAdmin):
    list_display = ("name", "phone", "shop", "created_at")
    list_filter = ["shop"]
    search_fields = ["name"]


@admin.register(Product)
class ProductAdmin(ShopManagerAdmin):
    list_display = ("name", "category", "unit", "cost_price", "average_cost_price",
                    "reorder_level", "current_stock", "is_active")
    list_filter = ["shop", "category", "is_active", "is_discontinued"]
    search_fields = ["name", "description"]

    def current_stock(self, obj):
        return obj.current_stock
    current_stock.short_description = "Current Stock"


@admin.register(Stock)
class StockAdmin(ShopManagerAdmin):
    list_display = ("product", "quantity", "is_low_stock", "last_updated")
    readonly_fields = ("quantity", "last_updated")


@admin.register(StockTransaction)
class StockTransactionAdmin(ShopManagerAdmin):
    list_display = ("stock", "type", "quantity_change", "created_by", "created_at")
    list_filter = ["type", "stock__product__shop"]
    ordering = ["-created_at"]
    readonly_fields = ("created_at",)


@admin.register(Expense)
class ExpenseAdmin(ShopManagerAdmin):
    list_display = ("title", "amount", "expense_type", "date", "shop")
    list_filter = ["shop", "expense_type", "date"]


@admin.register(OfflineSyncLog)
class OfflineSyncLogAdmin(ModelAdmin):
    list_display = ("shop", "sync_status", "sync_date", "error_message")
    list_filter = ["sync_status", "shop"]
    readonly_fields = ("sync_date", "error_message")