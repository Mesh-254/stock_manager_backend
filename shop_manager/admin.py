"""
Django Admin Configuration for School Shop Inventory

Custom admin classes with:
- Shop-scoped permissions (SuperAdmin sees everything, ShopAdmin sees only own shop).
- Inline formsets for PurchaseItem and UsageItem.
- Custom links to template-based add/edit/detail views (keeps your existing HTML templates working).
- No legacy Sale fields.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.inlines.admin import TabularInline as UnfoldTabularInline

from .models import (
    Shop,
    Category,
    Supplier,
    Product,
    Stock,
    Purchase,
    PurchaseItem,
    Usage,
    UsageItem,
    Expense,
    OfflineSyncLog,
)
from accounts.models import UserRole


# =============================================================================
# BASE ADMIN FOR SHOP-SCOPED MODELS
# =============================================================================
class ShopScopedAdmin(ModelAdmin):
    """
    Base admin for all shop-owned models.
    Automatically filters querysets and enforces permissions.
    """

    def has_module_permission(self, request):
        if not request.user.is_staff:
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.SHOP_ADMIN)

    def has_view_permission(self, request, obj=None):
        if not self.has_module_permission(request):
            return False
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        if obj is None:
            return True  # changelist allowed
        return getattr(obj, "shop", None) == request.user.shop

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == UserRole.SUPER_ADMIN:
            return qs
        if request.user.role == UserRole.SHOP_ADMIN and request.user.shop:
            if hasattr(self.model, "shop"):
                return qs.filter(shop=request.user.shop)
        return qs.none()

    def save_model(self, request, obj, form, change):
        if not change and request.user.role == UserRole.SHOP_ADMIN and hasattr(obj, "shop"):
            obj.shop = request.user.shop
        super().save_model(request, obj, form, change)


# =============================================================================
# PURCHASE ADMIN + INLINE
# =============================================================================
class PurchaseItemInline(UnfoldTabularInline):
    model = PurchaseItem
    extra = 0
    fields = ("product", "quantity", "unit_cost_price")
    can_delete = True


@admin.register(Purchase)
class PurchaseAdmin(ShopScopedAdmin):
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

    total_amount_formatted.short_description = "Total"


@admin.register(PurchaseItem)
class PurchaseItemAdmin(ShopScopedAdmin):
    list_display = ("purchase", "product", "quantity", "unit_cost_price", "total_cost")
    search_fields = ("product__name",)


# =============================================================================
# USAGE ADMIN + INLINE
# =============================================================================
class UsageItemInline(TabularInline):
    model = UsageItem
    extra = 0
    fields = ("product", "quantity")
    can_delete = True


@admin.register(Usage)
class UsageAdmin(ShopScopedAdmin):
    list_display = ("id_link", "usage_date", "recorded_by", "total_cost", "edit_link")
    list_filter = ("usage_date", "shop")
    search_fields = ("id",)
    date_hierarchy = "usage_date"
    readonly_fields = ("total_cost",)
    inlines = [UsageItemInline]

    def id_link(self, obj):
        url = reverse("detail_sale", kwargs={"sale_id": obj.pk})  # keep legacy template name
        return format_html('<a href="{}" class="font-medium">{}</a>', url, obj.pk)

    id_link.short_description = "ID"

    def edit_link(self, obj):
        url = reverse("edit_sale", kwargs={"sale_id": obj.pk})  # keep legacy template name
        return format_html('<a href="{}" class="text-blue-600">Edit</a>', url)

    edit_link.short_description = "Actions"


@admin.register(UsageItem)
class UsageItemAdmin(ShopScopedAdmin):
    list_display = ("usage", "product", "quantity", "unit_cost_price", "cost")
    search_fields = ("product__name",)


# =============================================================================
# OTHER MODELS
# =============================================================================
@admin.register(Shop)
class ShopAdmin(ModelAdmin):
    list_display = ("name", "owner", "country", "currency_code", "is_active")
    search_fields = ("name", "owner__full_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Category)
class CategoryAdmin(ShopScopedAdmin):
    list_display = ("name", "shop", "description")


@admin.register(Supplier)
class SupplierAdmin(ShopScopedAdmin):
    list_display = ("name", "phone", "shop")


@admin.register(Product)
class ProductAdmin(ShopScopedAdmin):
    list_display = ("name", "category", "unit", "cost_price", "average_cost_price", "reorder_level", "current_stock")
    search_fields = ("name", "category__name")
    list_filter = ("category", "is_active", "is_discontinued", "shop")

    def current_stock(self, obj):
        return obj.current_stock

    current_stock.short_description = "Current Stock"


@admin.register(Stock)
class StockAdmin(ShopScopedAdmin):
    list_display = ("product", "quantity", "is_low_stock", "last_updated")
    readonly_fields = ("quantity", "last_updated")


@admin.register(Expense)
class ExpenseAdmin(ShopScopedAdmin):
    list_display = ("title", "amount", "expense_type", "date", "shop")
    list_filter = ("expense_type", "date", "shop")


@admin.register(OfflineSyncLog)
class OfflineSyncLogAdmin(ModelAdmin):
    list_display = ("shop", "sync_status", "sync_date")
    list_filter = ("sync_status", "shop")
    readonly_fields = ("sync_date", "error_message")