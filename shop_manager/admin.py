from django.contrib import admin
from shop_manager.signals import recalculate_purchase_total
from django.urls import reverse
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.contrib.inlines.admin import TabularInline as UnfoldTabularInline
from django.contrib.admin import SimpleListFilter
from django.db.models import Sum, F
from django.core.exceptions import FieldDoesNotExist
from .models import (
    Brand,
    SubscriptionPlan,
    Shop,
    Category,
    Supplier,
    Product,
    Stock,
    Purchase,
    PurchaseItem,
    Sale,
    SaleItem,
    Expense,
    OfflineSyncLog,
    VehicleMake,
    VehicleModel,
    Returns,
)
from accounts.models import User, UserRole
from django.utils.html import format_html
from unfold.decorators import display


# =============================================================================
# Base class for shop-scoped models
# =============================================================================
class ShopScopedAdmin(ModelAdmin):
    """
    Base admin class for models that belong to a shop.
    - SuperAdmin: full access
    - ShopAdmin: access only to their own shop's objects
    - Others: no access
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
        if request.user.role == UserRole.SHOP_ADMIN:
            # Changelist (obj is None) → allowed, queryset will filter
            if obj is None:
                return True
            # Object detail → check shop match
            return hasattr(obj, "shop") and obj.shop == request.user.shop
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.role == UserRole.SUPER_ADMIN:
            return qs.all()

        if request.user.role == UserRole.SHOP_ADMIN and request.user.shop:
            try:
                self.model._meta.get_field("shop")
                return qs.filter(shop=request.user.shop)
            except FieldDoesNotExist:
                # Global model (no shop field) → show all objects
                return qs.all()

        # No permission (e.g., cashier or no shop assigned)
        return qs.none()

        
    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj) or ()
        if request.user.role == UserRole.SHOP_ADMIN and obj:
            # Prevent ShopAdmin from changing the shop of existing objects
            if hasattr(obj, "shop"):
                readonly += ("shop",)
        return readonly

    # Optional: Auto-assign shop when ShopAdmin creates a new object
    def save_model(self, request, obj, form, change):
        if not change and request.user.role == UserRole.SHOP_ADMIN:
            if hasattr(obj, "shop") and not obj.shop:
                obj.shop = request.user.shop
        super().save_model(request, obj, form, change)


# =============================================================================
# Inlines (unchanged for now)
# =============================================================================


class ReturnsInline(TabularInline):
    model = Returns
    extra = 0
    fields = ("return_date", "reason", "refund_amount", "resolved")
    # readonly_fields = ("return_date")


# ────────────────────────────────────────────────
#  Inline for Purchase Items – must come BEFORE PurchaseAdmin
# ────────────────────────────────────────────────
class PurchaseItemInline(
    UnfoldTabularInline
):  # Or UnfoldStackedInline for vertical layout
    model = PurchaseItem
    extra = 0  # No empty rows
    fields = ("product", "brand", "quantity", "unit_cost_price")  # Adjust as needed
    readonly_fields = ()  # Add any if needed
    can_delete = True  # Allow deleting individual items from the inline

    # Optional: default cost price from product
    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        formset.form.base_fields["unit_cost_price"].initial = (
            None  # or set default logic
        )
        return formset


# ────────────────────────────────────────────────
#  Purchase Admin – must come AFTER the inline definition
# ────────────────────────────────────────────────
@admin.register(Purchase)
class PurchaseAdmin(ShopScopedAdmin):
    list_display = (
        "id_link",
        "shop",
        "supplier",
        "purchase_date",
        "total_amount_formatted",
        "payment_status",
        "payment_method",
        "edit_link",
        "item_count",
    )
    list_filter = (
        "payment_status",
        "payment_method",
        "purchase_date",
        "shop",
        "supplier",
    )

    list_display_links = ("id_link",)

    search_fields = ("supplier__name", "id")
    date_hierarchy = "purchase_date"
    ordering = ("-purchase_date",)

    readonly_fields = ("total_amount", "created_by")

    # CRITICAL: This makes inline appear
    inlines = [PurchaseItemInline]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "shop",
                    "supplier",
                    "purchase_date",
                    "payment_status",
                    "payment_method",
                )
            },
        ),
        (
            "Auto-calculated",
            {
                "fields": ("total_amount",),
                "classes": ("collapse",),
            },
        ),
    )

    class Media:
        js = ('shop_manager/js/admin_row_click.js',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("shop", "supplier", "created_by").prefetch_related(
            "items__product"
        )
    
    def edit_link(self, obj):
        if not obj.pk:
            return "-"
        url = reverse('edit_purchase', kwargs={'purchase_id': obj.pk})  # Uses name, auto-correct path
        return format_html('<a href="{}" class="text-blue font-medium">Update</a>', url)
    edit_link.short_description = "Actions"

    def id_link(self, obj):
        if not obj.pk:
            return "-"
        url = reverse('detail_purchase', kwargs={'purchase_id': obj.pk})
        return format_html('<a href="{}" class="font-medium text-primary hover:underline">{}</a>', url, obj.pk)
    id_link.short_description = "ID"
    id_link.admin_order_field = "id"  # Allow sorting by ID

    def save_model(self, request, obj, form, change):
        if not change:  # New purchase
            obj.created_by = request.user
            if request.user.role == UserRole.SHOP_ADMIN and not obj.shop:
                obj.shop = request.user.shop
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model != PurchaseItem:
            return super().save_formset(request, form, formset, change)

        instances = formset.save(commit=False)
        for instance in instances:
            if not instance.pk:
                instance.purchase = form.instance  # Critical link
            instance.save()

        for obj in formset.deleted_objects:
            obj.delete()

        formset.save_m2m()

        # Recalculate total (your signal will also do this, but safety net)
        if hasattr(form.instance, "items"):
            recalculate_purchase_total(form.instance)

        if form.instance.items.exists():
            self.message_user(
                request,
                f"Purchase saved with {form.instance.items.count()} items. Stock updated.",
                level="success",
            )

    # Display helpers
    def total_amount_formatted(self, obj):
        return f"{obj.total_amount:,.2f}" if obj.total_amount else "0.00"

    total_amount_formatted.short_description = "Total Amount"

    def item_count(self, obj):
        return obj.items.count()

    item_count.short_description = "# Items"


@admin.register(PurchaseItem)
class PurchaseItemAdmin(ModelAdmin):
    list_display = ("purchase", "product", "quantity", "unit_cost_price", "total_cost")
    list_filter = ("purchase__purchase_date", "product")
    search_fields = ("product__name", "purchase__id")
    autocomplete_fields = ["product", "purchase"]

    def total_cost(self, obj):
        return obj.quantity * obj.unit_cost_price

    total_cost.short_description = "Total Cost"

    def has_view_permission(self, request, obj=None):
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        if obj is None:
            return True  # Allow changelist
        return obj.purchase.shop == request.user.shop

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)


class SaleItemInline(StackedInline):
    model = SaleItem
    extra = 1
    fields = ("product", "quantity", "unit_selling_price")
    readonly_fields = ("unit_selling_price",)


@admin.register(VehicleMake)
class VehicleMakeAdmin(ShopScopedAdmin):
    list_display = ("name", "model_count")
    list_filter = ("name",)
    search_fields = ("name",)
    ordering = ("name",)

    def model_count(self, obj):
        return obj.models.count()

    model_count.short_description = "Models"


@admin.register(VehicleModel)
class VehicleModelAdmin(ShopScopedAdmin):
    list_display = (
        "make",
        "name",
        "year_range",
    )
    list_filter = ("make", "name", "year_start")
    search_fields = ("name", "make__name")
    ordering = ("make__name", "name")

    def year_range(self, obj):
        return f"{obj.year_start}-{obj.year_end or 'Present'}"

    year_range.short_description = "Years"


@admin.register(SaleItem)
class SaleItemAdmin(ShopScopedAdmin):
    list_display = (
        "product",
        "sale",
        "quantity",
        "unit_selling_price",
        "total",
        "return_count",
    )
    list_filter = ("product__category", "sale__sale_date")
    inlines = [ReturnsInline]

    def total(self, obj):
        return obj.quantity * obj.unit_selling_price

    def return_count(self, obj):
        return obj.returns.count()


# =============================================================================
# Model Admin registrations
# =============================================================================


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(ModelAdmin):
    """
    Global plans — only SuperAdmin should see/manage these
    """

    list_display = (
        "name",
        "price_per_month",
        "user_limit",
        "product_limit",
        "shop_limit",
    )
    search_fields = ("name",)

    def has_module_permission(self, request):
        return request.user.is_staff and request.user.role == UserRole.SUPER_ADMIN

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(Shop)
class ShopAdmin(ModelAdmin):
    """
    Admin for Shop model — no shop-based filtering needed here
    """

    list_display = ("name", "owner", "subscription_plan", "is_active", "created_at")
    list_filter = ("is_active", "country", "subscription_plan")
    search_fields = ("name", "owner__email", "owner__full_name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "owner",
                    "description",
                    "logo",
                    "currency_code",
                    "country",
                )
            },
        ),
        ("Subscription", {"fields": ("subscription_plan", "is_active")}),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """
        SuperAdmin sees all shops.
        ShopAdmin sees only their own shop.
        """
        qs = super().get_queryset(request)

        if request.user.role == UserRole.SUPER_ADMIN:
            return qs

        if request.user.role == UserRole.SHOP_ADMIN:
            # ShopAdmin can only see their own shop
            return qs.filter(owner=request.user)

        return qs.none()

    def has_view_permission(self, request, obj=None):
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        if request.user.role == UserRole.SHOP_ADMIN:
            return obj is None or obj.owner == request.user
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_add_permission(self, request):
        return request.user.role == UserRole.SUPER_ADMIN


@admin.register(Category)
class CategoryAdmin(ShopScopedAdmin):
    list_display = ("name", "shop", "description")
    search_fields = ("name", "shop__name")
    list_filter = ("shop",)


@admin.register(Supplier)
class SupplierAdmin(ShopScopedAdmin):
    list_display = ("name", "phone", "shop")
    search_fields = ("name",)


@admin.register(Brand)
class BrandAdmin(ShopScopedAdmin):
    list_display = ("name", "country_of_origin", "is_active")
    list_filter = ("is_active", "country_of_origin")
    search_fields = ("name",)
    ordering = ("name",)

    
    


@admin.register(Product)
class ProductAdmin(ShopScopedAdmin):
    list_display = (
        "name",
        "category",
        "cost_price",
        "selling_price",
        "shop",
        "reorder_level",
        "stock_quantity",
        "is_active",
    )
    search_fields = ("name",)
    list_filter = ("category", "is_active", "shop")
    list_per_page = 25

    def stock_quantity(self, obj):
        return obj.stock.quantity if hasattr(obj, "stock") and obj.stock else 0

    stock_quantity.short_description = "Current Stock"


# ────────────────────────────────────────────────
# For Stock (and similar models that go through product.shop)
# ────────────────────────────────────────────────
class ProductRelatedScopedAdmin(ModelAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == UserRole.SUPER_ADMIN:
            return qs
        if request.user.role == UserRole.SHOP_ADMIN:
            return qs.filter(product__shop=request.user.shop)
        return qs.none()

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff


@admin.register(Stock)
class StockAdmin(ProductRelatedScopedAdmin):
    list_display = ("product", "quantity", "get_shop")
    search_fields = ("product__name",)
    list_filter = ("product__category", "product__shop")
    readonly_fields = ("quantity",)

    def get_shop(self, obj):
        return obj.product.shop if obj.product and obj.product.shop else "-"

    get_shop.short_description = "Shop"
    get_shop.admin_order_field = "product__shop"

@admin.register(Sale)
class SaleAdmin(ShopScopedAdmin):
    list_display = (
        "id_link",          # Custom ID column (links to details)
        "sale_date",
        "sold_by",
        "total_amount",
        "payment_status",
        "payment_method",
        "discount",
        "update_button",    # New Update button column
    )
    list_filter = ("sale_date", "payment_status", "payment_method", "shop")
    search_fields = ("id", "sold_by__username")
    date_hierarchy = "sale_date"
    readonly_fields = ("total_amount",)  # Optional: prevent accidental edit

    # Disable default edit links (we're using custom ones)
    list_display_links = None

    @display(description="ID", ordering="id")
    def id_link(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("detail_sale", kwargs={"sale_id": obj.pk})
        return format_html(
            '<a href="{}" class="text-primary font-bold hover:underline">{}</a>',
            url,
            obj.id,
        )
    id_link.short_description = "ID"

    @display(description="Actions")
    def update_button(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("edit_sale", kwargs={"sale_id": obj.pk})
        return format_html(
            '<a href="{}" class="inline-block px-4 py-2 bg-success text-white font-medium rounded hover:bg-green-700 transition shadow">Update</a>',
            url,
        )
    update_button.short_description = "Actions"

@admin.register(Returns)
class ReturnsAdmin(ShopScopedAdmin):
    list_display = ("sale_item", "return_date", "reason", "refund_amount", "resolved")
    list_filter = ("reason", "resolved", "return_date")
    search_fields = ("sale_item__product__name",)
    readonly_fields = ("return_date",)
    ordering = ("-return_date",)


@admin.register(Expense)
class ExpenseAdmin(ShopScopedAdmin):
    list_display = ("title", "amount", "expense_type", "date", "shop")
    list_filter = ("expense_type", "shop", "date")


@admin.register(OfflineSyncLog)
class OfflineSyncLogAdmin(ModelAdmin):
    list_display = ("shop", "sync_status", "sync_date", "error_message")
    list_filter = ("sync_status", "shop")
    readonly_fields = ("sync_date", "error_message")

    def has_module_permission(self, request):
        if not request.user.is_staff:
            return False
        return request.user.role in (UserRole.SUPER_ADMIN, UserRole.SHOP_ADMIN)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.role == UserRole.SUPER_ADMIN:
            return qs
        if request.user.role == UserRole.SHOP_ADMIN:
            return qs.filter(shop=request.user.shop)
        return qs.none()


# =============================================================================
# Reports Section (Custom Admin Views)
# =============================================================================


class ReportAdmin(ModelAdmin):
    """
    Base class for read-only report-style admin pages
    """

    change_list_template = "admin/shop_manager/report_change_list.html"
    list_display = ("title", "period", "total", "download_link")
    list_filter = ()
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class VehicleMakeFilter(SimpleListFilter):
    title = "Vehicle Make"
    parameter_name = "vehicle_make"

    def lookups(self, request, model_admin):
        return VehicleMake.objects.all().values_list("id", "name")

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(product__vehicle_compatibility__make_id=self.value())
        return queryset
