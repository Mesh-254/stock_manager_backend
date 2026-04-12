"""
shop_manager/admin.py

Django Admin Configuration for School Shop Inventory System

Key Improvements:
- Auto-selects the current logged-in user's shop when creating records.
- Makes the 'shop' field read-only and pre-filled for ShopAdmin users.
- SuperAdmin still sees the full dropdown (can choose any shop).
- Prevents cross-shop data leaks in the admin interface.
- Works with Unfold admin theme.
- Heavily documented and consistent with your DRF permissions.
"""

from django.utils import timezone
from decimal import Decimal

from django.contrib import admin
from django import forms
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.contrib.inlines.admin import TabularInline as UnfoldTabularInline
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField
from django.db.models.functions import NullIf
from .models import (
    Shop, Category, Supplier, Product, Stock, StockTransaction,
    Purchase, PurchaseItem, Usage, UsageItem, Expense, OfflineSyncLog, DailyStudentRecord
)


# =============================================================================
# BASE ADMIN CLASS WITH AUTO-SHOP & READ-ONLY BEHAVIOR
# =============================================================================
class ShopManagerAdmin(ModelAdmin):
    """
    Base admin class that:
    1. Filters queryset to user's own shop (ShopAdmin)
    2. Auto-selects and makes 'shop' field read-only for ShopAdmin
    3. Gives full access to SuperAdmin
    """

    def has_module_permission(self, request):
        if not request.user.is_authenticated:
            return False
        return request.user.role in ("SuperAdmin", "ShopAdmin")

    def has_view_permission(self, request, obj=None):
        if not self.has_module_permission(request):
            return False
        if request.user.role == "SuperAdmin":
            return True
        if obj is None:
            return True
        return getattr(obj, "shop", None) == getattr(request.user, "shop", None)

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == "SuperAdmin":
            return qs
        user_shop = getattr(request.user, "shop", None)
        if user_shop and hasattr(self.model, "shop"):
            return qs.filter(shop=user_shop)
        return qs.none()

    def save_model(self, request, obj, form, change):
        """Auto-assign shop for ShopAdmin when creating new objects."""
        if not change and request.user.role == "ShopAdmin" and hasattr(obj, "shop"):
            obj.shop = request.user.shop
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Auto-select current user's shop and make it read-only for ShopAdmin.
        SuperAdmin gets full dropdown.
        """
        if db_field.name == "shop":
            user = request.user
            user_shop = getattr(user, "shop", None)

            if user.role == "ShopAdmin" and user_shop:
                # Pre-fill with user's shop and disable the field
                kwargs["queryset"] = Shop.objects.filter(id=user_shop.id)
                kwargs["initial"] = user_shop.id
                # Make it read-only in the form
                kwargs["disabled"] = True
                # Optional: You can also hide it completely if you prefer
                kwargs["widget"] = forms.HiddenInput()
            elif user.role == "SuperAdmin":
                # Full choice for SuperAdmin
                kwargs["queryset"] = Shop.objects.all()

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        """Make 'shop' field read-only in change view for ShopAdmin."""
        readonly_fields = super().get_readonly_fields(request, obj)
        if request.user.role == "ShopAdmin" and obj and hasattr(obj, "shop"):
            readonly_fields = list(readonly_fields) + ["shop"]
        return readonly_fields

# =============================================================================
# PURCHASE ADMIN + INLINE
# =============================================================================
class PurchaseItemInline(UnfoldTabularInline):
    model = PurchaseItem
    extra = 0
    fields = ("product", "quantity", "unit_cost_price")
    can_delete = True
    verbose_name = "Purchase Item"
    verbose_name_plural = "Purchase Items"


@admin.register(Purchase)
class PurchaseAdmin(ShopManagerAdmin):
    """
    Cleaned Purchase admin view:
    - Removed ID and Shop columns (as requested)
    - Added Product count + Total Quantity summary
    - Better visual hierarchy with custom methods
    - Kept essential information for quick scanning
    """
    list_display = (
        "purchase_date",
        "supplier",
        "items_summary",           # New: Shows products and quantities
        "total_quantity",          # New: Total items bought
        "total_amount_formatted",
        "payment_status",
        "edit_link",
    )
    
    list_filter = ("payment_status", "payment_method", "purchase_date", "supplier")
    search_fields = ("supplier__name", "items__product__name", "note")
    date_hierarchy = "purchase_date"
    ordering = ("-purchase_date",)
    
    readonly_fields = ("total_amount", "created_by")
    inlines = [PurchaseItemInline]

    # ===================================================================
    # Custom display methods
    # ===================================================================

    def items_summary(self, obj):
        """Shows first few products with quantities in a nice format"""
        items = obj.items.select_related("product")[:4]  # Limit for clean display
        if not items:
            return "—"
        
        summary = []
        for item in items:
            summary.append(f"{item.product.name} ({item.quantity})")
        
        result = ", ".join(summary)
        if obj.items.count() > 4:
            result += f" +{obj.items.count() - 4} more"
        return result
    items_summary.short_description = "Products Purchased"
    items_summary.admin_order_field = "items__product__name"  # Optional

    def total_quantity(self, obj):
        """Total quantity of all items in this purchase"""
        total = obj.items.aggregate(total=Sum("quantity"))["total"] or 0
        return f"{total:,.0f}"
    total_quantity.short_description = "Total Qty"
    total_quantity.admin_order_field = "total_quantity"  # Will need annotation if sorting required

    def total_amount_formatted(self, obj):
        return f"KES {obj.total_amount:,.2f}" if obj.total_amount else "KES 0.00"
    total_amount_formatted.short_description = "Total Amount"

    def edit_link(self, obj):
        url = reverse("edit_purchase", kwargs={"purchase_id": obj.pk})
        return format_html(
            '<a href="{}" class="text-sky-600 hover:text-sky-700 font-medium">Edit</a>', 
            url
        )
    edit_link.short_description = "Actions"

    # Optional: Add annotation for better performance on total_quantity sorting
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Annotate total quantity for better performance
        return qs.annotate(
            total_quantity=Sum("items__quantity")
        )

@admin.register(PurchaseItem)
class PurchaseItemAdmin(ShopManagerAdmin):
    list_display = ("purchase", "product", "quantity", "unit_cost_price", "total_cost")
    search_fields = ("product__name",)


# =============================================================================
# USAGE ADMIN (Improved for Logistics)
# =============================================================================
class UsageItemInline(UnfoldTabularInline):
    model = UsageItem
    extra = 0
    fields = ("product", "quantity")
    can_delete = True
    verbose_name = "Usage Item"
    verbose_name_plural = "Usage Items"


@admin.register(Usage)
class UsageAdmin(ShopManagerAdmin):
    """
    Enhanced Usage admin for logistics visibility:
    - Shows key operational information at a glance
    - Focuses on cost control, consumption volume, and usage patterns
    - Clean, professional layout with important metrics first
    """
    list_display = (
        "usage_date",
        "recorded_by",
        "items_summary",           # Products consumed + quantities
        "total_quantity",          # Total units used (very important for logistics)
        "total_cost_formatted",    # Cost impact
        "average_cost_per_unit",   # New: Efficiency metric
        "edit_link",
    )

    list_filter = ("usage_date", "recorded_by")
    search_fields = ("note", "recorded_by__full_name", "items__product__name")
    date_hierarchy = "usage_date"
    ordering = ("-usage_date",)

    readonly_fields = ("total_cost",)
    inlines = [UsageItemInline]

    # ===================================================================
    # Custom display methods for logistics insights
    # ===================================================================

    def items_summary(self, obj):
        """Clean summary of consumed products with quantities"""
        items = obj.items.select_related("product")[:5]
        if not items:
            return "—"

        summary = [f"{item.product.name} ({item.quantity})" for item in items]
        result = ", ".join(summary)

        if obj.items.count() > 5:
            result += f" +{obj.items.count() - 5} more"

        return result
    items_summary.short_description = "Items Used"
    items_summary.admin_order_field = "items__product__name"

    def total_quantity(self, obj):
        """Total number of units consumed - critical for logistics & inventory planning"""
        total = obj.items.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        return f"{total:,.0f}"
    total_quantity.short_description = "Total Qty Used"
    total_quantity.admin_order_field = "total_quantity"

    def total_cost_formatted(self, obj):
        """Total cost of usage"""
        return f"KES {obj.total_cost:,.0f}" if obj.total_cost else "KES 0"
    total_cost_formatted.short_description = "Total Cost"
    total_cost_formatted.admin_order_field = "total_cost"

    def average_cost_per_unit(self, obj):
        """Key logistics metric: Average cost per unit consumed"""
        total_qty = obj.items.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        if total_qty == 0:
            return "—"
        
        avg_cost = obj.total_cost / total_qty
        return f"KES {avg_cost:,.2f}"
    average_cost_per_unit.short_description = "Avg Cost/Unit"
    average_cost_per_unit.admin_order_field = "avg_cost_per_unit"   # Will be annotated

    def edit_link(self, obj):
        url = reverse("edit_usage", kwargs={"usage_id": obj.pk})
        return format_html(
            '<a href="{}" class="text-sky-600 hover:text-sky-700 font-medium">Edit</a>', 
            url
        )
    edit_link.short_description = "Actions"

    # ===================================================================
    # Optimize queryset for performance + annotations
    # ===================================================================
    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related(
            "recorded_by"
        ).prefetch_related("items__product")

        # Annotate important metrics for better performance and sorting
        return qs.annotate(
            total_quantity=Sum("items__quantity"),
            total_items=Count("items"),
            avg_cost_per_unit=ExpressionWrapper(
                F("total_cost") / NullIf(Sum("items__quantity"), 0),
                output_field=DecimalField()
            )
        )


@admin.register(UsageItem)
class UsageItemAdmin(ShopManagerAdmin):
    """Keep UsageItem admin simple and clean"""
    list_display = ("usage", "product", "quantity", "cost")
    list_filter = ("usage__usage_date",)
    search_fields = ("product__name", "usage__recorded_by__full_name")
    ordering = ("-usage__usage_date",)

    
# =============================================================================
# SHOP ADMIN (special case)
# =============================================================================
@admin.register(Shop)
class ShopAdmin(ShopManagerAdmin):
    list_display = ("name", "owner", "country", "currency_code", "is_active", "created_at")
    list_filter = ("is_active", "country", "currency_code")
    search_fields = ("name", "description")
    ordering = ["name"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == "SuperAdmin":
            return qs
        user_shop = getattr(request.user, "shop", None)
        if user_shop:
            return qs.filter(id=user_shop.id)
        return qs.none()


# =============================================================================
# OTHER MODELS (inherit auto-shop behavior)
# =============================================================================
@admin.register(Category)
class CategoryAdmin(ShopManagerAdmin):
    list_display = ("name", "shop", "description")
    list_filter = ["shop"]
    search_fields = ["name"]
    # Shop field will be auto-filled + read-only thanks to base class


@admin.register(Supplier)
class SupplierAdmin(ShopManagerAdmin):
    list_display = ("name", "phone", "shop", "created_at")
    list_filter = ["shop"]
    search_fields = ["name"]

@admin.register(Product)
class ProductAdmin(ShopManagerAdmin):
    """
    Product management in admin with smart auto-handling:
    - average_cost_price is read-only and auto-managed
    - created_by is automatically set to current user and made read-only
    - Fixed KeyError by properly including fields in the form
    """

    list_display = (
        "name", 
        "category", 
        "unit", 
        "cost_price", 
        "average_cost_price", 
        "reorder_level", 
        "current_stock", 
        "is_active",
        "created_by",
    )
    list_filter = ["shop", "category", "is_active", "is_discontinued"]
    search_fields = ["name", "description"]

    # Explicitly define which fields to show + readonly ones
    fields = (
        "shop",
        "name",
        "description",
        "category",
        "unit",
        "cost_price",
        "average_cost_price",
        "reorder_level",
        "is_active",
        "is_discontinued",
        "created_by",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("average_cost_price", "created_by", "current_stock", "created_at", "updated_at")

    def current_stock(self, obj):
        return obj.current_stock or "0.000"
    current_stock.short_description = "Current Stock"

    def get_form(self, request, obj=None, **kwargs):
        """
        Customize form to auto-set and disable 'created_by' and make 'average_cost_price' read-only.
        """
        form = super().get_form(request, obj, **kwargs)

        # For new products (create)
        if not obj:
            # Auto-set created_by to current user
            if 'created_by' in form.base_fields:
                form.base_fields['created_by'].initial = request.user
                form.base_fields['created_by'].disabled = True

            # Ensure average_cost_price starts as cost_price
            if 'cost_price' in form.base_fields and 'average_cost_price' in form.base_fields:
                form.base_fields['average_cost_price'].initial = form.base_fields['cost_price'].initial or Decimal("0.00")
                form.base_fields['average_cost_price'].disabled = True

        # For editing existing products
        else:
            if 'created_by' in form.base_fields:
                form.base_fields['created_by'].disabled = True
            if 'average_cost_price' in form.base_fields:
                form.base_fields['average_cost_price'].disabled = True

        return form

    def save_model(self, request, obj, form, change):
        """
        Final safety net: ensure created_by and average_cost_price are correctly set.
        """
        if not change:  # Creating new product
            if not getattr(obj, 'created_by', None):
                obj.created_by = request.user

            # Auto-set average_cost_price = cost_price on first creation
            if not obj.average_cost_price or obj.average_cost_price == Decimal("0.00"):
                obj.average_cost_price = obj.cost_price

        super().save_model(request, obj, form, change)


@admin.register(Stock)
class StockAdmin(ShopManagerAdmin):
    list_display = ("product", "quantity", "is_low_stock", "last_updated")
    readonly_fields = ("quantity", "last_updated")
    search_fields = ["product__name"]

    def get_queryset(self, request):
        """Filter stock by user's shop via product__shop"""
        qs = Stock.objects.select_related("product", "product__category")
        if request.user.role == "SuperAdmin":
            return qs
        user_shop = getattr(request.user, "shop", None)
        if user_shop:
            return qs.filter(product__shop=user_shop)
        return qs.none()

    # === Proper object-level permissions for Stock ===
    def has_view_permission(self, request, obj=None):
        if request.user.role == "SuperAdmin":
            return True
        if not obj:
            return True  # List view already filtered by get_queryset

        user_shop = getattr(request.user, "shop", None)
        if not user_shop:
            return False

        # Stock links to shop via product
        return getattr(obj.product, "shop", None) == user_shop

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

@admin.register(StockTransaction)
class StockTransactionAdmin(ShopManagerAdmin):
    list_display = ("stock", "type", "quantity_change", "created_by", "created_at")
    list_filter = ["type", "stock__product__shop"]
    ordering = ["-created_at"]
    readonly_fields = ("created_at",)
    search_fields = ["stock__product__name"]

    def get_queryset(self, request):
        qs = StockTransaction.objects.select_related("stock__product", "created_by")
        if request.user.role == "SuperAdmin":
            return qs
        user_shop = getattr(request.user, "shop", None)
        if user_shop:
            return qs.filter(stock__product__shop=user_shop)
        return qs.none()

    def has_view_permission(self, request, obj=None):
        if request.user.role == "SuperAdmin":
            return True
        if not obj:
            return True

        user_shop = getattr(request.user, "shop", None)
        if not user_shop:
            return False

        return getattr(obj.stock.product, "shop", None) == user_shop

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)


@admin.register(Expense)
class ExpenseAdmin(ShopManagerAdmin):
    list_display = ("title", "amount_formatted", "expense_type", "date", "incurred_by", "shop")
    list_filter = ("expense_type", "date", "shop")
    search_fields = ("title",)
    date_hierarchy = "date"
    ordering = ("-date",)

    def amount_formatted(self, obj):
        return f"KES {obj.amount:,.2f}"
    amount_formatted.short_description = "Amount"
    amount_formatted.admin_order_field = "amount"

    # Explicit shop scoping (this is the key fix)
    def get_queryset(self, request):
        qs = Expense.objects.select_related("shop", "incurred_by")
        if request.user.role == "SuperAdmin":
            return qs
        user_shop = getattr(request.user, "shop", None)
        if user_shop:
            return qs.filter(shop=user_shop)
        return qs.none()

    # Ensure object-level permission also works correctly
    def has_view_permission(self, request, obj=None):
        if request.user.role == "SuperAdmin":
            return True
        if obj is None:
            return True
        user_shop = getattr(request.user, "shop", None)
        return getattr(obj, "shop", None) == user_shop

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)


@admin.register(OfflineSyncLog)
class OfflineSyncLogAdmin(ModelAdmin):
    list_display = ("shop", "sync_status", "sync_date", "error_message")
    list_filter = ["sync_status", "shop"]
    readonly_fields = ("sync_date", "error_message")


# =============================================================================
# DAILY STUDENT RECORD ADMIN
# =============================================================================
@admin.register(DailyStudentRecord)
class DailyStudentRecordAdmin(ShopManagerAdmin):
    list_display = (
        "record_date",
        "students_present",
        "note",
        "recorded_by",
        "created_at",
    )
    list_filter = ("record_date", "recorded_by")
    search_fields = ("note", "recorded_by__full_name")
    date_hierarchy = "record_date"
    ordering = ("-record_date",)

    readonly_fields = ("recorded_by", "created_at", "updated_at")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # === AUTO-PREFILL TODAY'S DATE ON ADD ===
        if not obj:  # creating new record
            today = timezone.now().date()
            if 'record_date' in form.base_fields:
                form.base_fields['record_date'].initial = today

            if 'recorded_by' in form.base_fields:
                form.base_fields['recorded_by'].initial = request.user
                form.base_fields['recorded_by'].disabled = True

        return form

    def save_model(self, request, obj, form, change):
        if not change:  # Creating new
            if not getattr(obj, 'recorded_by', None):
                obj.recorded_by = request.user
            if not getattr(obj, 'shop', None) and hasattr(request.user, 'shop'):
                obj.shop = request.user.shop
        super().save_model(request, obj, form, change)