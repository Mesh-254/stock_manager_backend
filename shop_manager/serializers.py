"""
Serializers for Shop Management API

This module contains all DRF serializers for the school inventory system.
It provides:
- Hyperlinked serializers for browseable API navigation
- Separate serializers for list, detail, and write operations (best practice)
- Proper handling of nested items for Purchase and Usage
- Atomic transactions for data integrity
- Automatic stock updates and cost calculations

Key Design Decisions:
- Read-only fields prevent accidental modification of calculated values
- Write serializers handle complex creation logic (stock, average cost, etc.)
- Nested writable items with separate read representations for clean API responses
"""

from rest_framework import serializers
from decimal import Decimal
from django.db import transaction
from django.core.validators import FileExtensionValidator
from django.contrib.auth import get_user_model

User = get_user_model()  # Get the user model for owner relations

# Import all models from the current app
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
)


# =============================================================================
# SHOP SERIALIZER
# =============================================================================
class ShopSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for Shop model.
    Used for creating, updating, and listing shops in the API.
    """

    # Hyperlinked relation to the owner (User)
    owner = serializers.HyperlinkedRelatedField(
        queryset=User.objects.all(),
        view_name="user-detail",
        help_text="URL linking to the shop owner",
    )

    # Image field with validation for allowed formats
    logo = serializers.ImageField(
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"])],
        help_text="Shop logo image (JPG, JPEG, or PNG only)",
    )

    class Meta:
        model = Shop
        fields = [
            "url",
            "id",
            "owner",
            "name",
            "description",
            "country",
            "currency_code",
            "logo",
            "is_active",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "url": {"view_name": "shop-detail"},
        }


# =============================================================================
# CATEGORY SERIALIZER
# =============================================================================
class CategorySerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for Category model.
    Categories are shop-specific (unique per shop).
    """

    shop = serializers.HyperlinkedRelatedField(
        queryset=Shop.objects.all(),
        view_name="shop-detail",
        help_text="URL of the shop this category belongs to",
    )

    class Meta:
        model = Category
        fields = ["url", "id", "shop", "name", "description"]
        extra_kwargs = {
            "url": {"view_name": "category-detail"},
        }


# =============================================================================
# SUPPLIER SERIALIZER
# =============================================================================
class SupplierSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for Supplier model.
    Used when managing suppliers for purchases.
    """

    shop = serializers.HyperlinkedRelatedField(
        queryset=Shop.objects.all(),
        view_name="shop-detail",
        help_text="URL of the shop this supplier is associated with",
    )

    class Meta:
        model = Supplier
        fields = ["url", "id", "shop", "name", "phone", "address", "created_at"]
        extra_kwargs = {
            "url": {"view_name": "supplier-detail"},
        }


# =============================================================================
# PRODUCT SERIALIZERS
# =============================================================================


class ProductListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing multiple products.
    Includes computed fields like current_stock and reorder status.
    """

    category = CategorySerializer(read_only=True)
    current_stock = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        source="current_stock",
        read_only=True,
        help_text="Current available stock quantity",
    )
    needs_reorder = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "category",
            "unit",
            "cost_price",
            "average_cost_price",
            "reorder_level",
            "current_stock",
            "needs_reorder",
            "is_active",
            "is_discontinued",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "current_stock",
            "needs_reorder",
            "created_at",
            "is_discontinued",
        ]

    def get_needs_reorder(self, obj):
        """Determine if product stock is below reorder level"""
        return obj.current_stock <= obj.reorder_level


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for a single product view.
    Includes all fields and nested related data.
    """

    category = CategorySerializer(read_only=True)
    current_stock = serializers.DecimalField(
        max_digits=12, decimal_places=3, source="current_stock", read_only=True
    )
    created_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = [
            "id",
            "current_stock",
            "created_at",
            "updated_at",
            "created_by",
            "is_discontinued",
            "discontinued_at",
            "shop",
        ]


class ProductWriteSerializer(serializers.ModelSerializer):
    """
    Serializer used for creating and updating products.
    Handles initial stock creation (only on create).
    """

    initial_stock = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        write_only=True,
        required=False,
        default=0,
        min_value=0,
        help_text="Initial stock quantity (only used when creating a new product)",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "description",
            "category",
            "unit",
            "cost_price",
            "reorder_level",
            "initial_stock",
        ]

    def create(self, validated_data):
        """
        Custom create logic:
        - Sets shop and created_by from request user
        - Initializes average_cost_price = cost_price
        - ALWAYS creates a Stock record (0 or initial_stock)
        - Uses update_stock() when initial_stock > 0 so we get a proper audit trail
        """
        initial_stock = validated_data.pop("initial_stock", Decimal("0"))
        user = self.context["request"].user

        product = Product.objects.create(
            **validated_data,
            shop=user.shop if hasattr(user, "shop") else None,
            created_by=user,
            average_cost_price=validated_data["cost_price"],
        )

        from .utils import update_stock

        if initial_stock > 0:
            # Create stock + audit transaction (best for traceability)
            update_stock(
                product=product,
                quantity_change=initial_stock,
                transaction_type="initial",          # will show as "unknown" until you add it to choices
                reason="Initial stock on product creation",
                reference="product creation",
                user=user,
            )
        else:
            # Just guarantee the zero stock record exists
            Stock.objects.get_or_create(
                product=product,
                defaults={"quantity": Decimal("0.00")}
            )

        return product

# =============================================================================
# STOCK SERIALIZERS
# =============================================================================


class StockTransactionSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for stock movement history.
    Shows human-readable product and user information.
    """

    product_name = serializers.CharField(source="stock.product.name", read_only=True)
    product_id = serializers.UUIDField(source="stock.product.id", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, allow_null=True
    )

    class Meta:
        model = StockTransaction
        fields = [
            "id",
            "type",
            "quantity_change",
            "reason",
            "reference",
            "created_by_name",
            "created_at",
            "product_id",
            "product_name",
        ]
        read_only_fields = fields  # All fields are read-only (immutable history)


class StockSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for Stock model (current stock levels).
    """

    product = serializers.HyperlinkedRelatedField(
        queryset=Product.objects.all(), view_name="product-detail"
    )
    low_stock = serializers.BooleanField(
        source="is_low_stock",
        read_only=True,
        help_text="True if current quantity is at or below reorder level",
    )

    class Meta:
        model = Stock
        fields = ["url", "id", "product", "quantity", "last_updated", "low_stock"]
        extra_kwargs = {
            "url": {"view_name": "stock-detail"},
        }


# =============================================================================
# PURCHASE SERIALIZERS
# =============================================================================


class PurchaseItemSerializer(serializers.ModelSerializer):
    """
    Serializer for individual purchase line items.
    """

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    total_cost = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseItem
        fields = ["id", "product", "quantity", "unit_cost_price", "total_cost"]

    def get_total_cost(self, obj):
        """Calculate total cost for this purchase item"""
        return obj.total_cost


class PurchaseSerializer(serializers.ModelSerializer):
    """
    Main serializer for Purchase (stock inflow).
    Handles nested items and triggers stock update + average cost recalculation.
    """

    shop = serializers.PrimaryKeyRelatedField(
        queryset=Shop.objects.all(),
        required=False,
        help_text="Auto-set for ShopAdmin users",
    )
    supplier = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.all(), allow_null=True
    )
    created_by = serializers.HiddenField(default=serializers.CurrentUserDefault())

    # Nested writable items (for POST) and readable items (for GET)
    items = PurchaseItemSerializer(many=True, write_only=True)
    items_read = PurchaseItemSerializer(source="items", many=True, read_only=True)

    class Meta:
        model = Purchase
        fields = [
            "id",
            "shop",
            "supplier",
            "purchase_date",
            "payment_status",
            "payment_method",
            "total_amount",
            "created_by",
            "items",
            "items_read",
        ]
        read_only_fields = ["id", "total_amount", "created_by"]

    @transaction.atomic
    def create(self, validated_data):
        """
        Atomic creation of Purchase + Items + Stock update.
        Ensures data consistency even if something fails midway.
        """
        items_data = validated_data.pop("items")
        request = self.context["request"]

        # Auto-populate user and shop
        validated_data["created_by"] = request.user
        if hasattr(request.user, "shop") and request.user.shop:
            validated_data["shop"] = request.user.shop

        purchase = Purchase.objects.create(**validated_data)

        # Create all purchase items
        for item_data in items_data:
            PurchaseItem.objects.create(purchase=purchase, **item_data)

        # Update totals and stock (weighted average cost + quantity)
        purchase.update_total()
        purchase.update_stock(user=request.user)

        return purchase


# =============================================================================
# USAGE SERIALIZERS  (Daily Consumption)
# =============================================================================
class UsageItemSerializer(serializers.ModelSerializer):
    """
    Serializer for individual usage/consumption items.
    Only product and quantity are required from the client.
    """

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    class Meta:
        model = UsageItem
        fields = ["id", "product", "quantity"]
        read_only_fields = ["id"]


class UsageSerializer(serializers.ModelSerializer):
    """
    Serializer for Usage (stock outflow / daily consumption).
    Critical for school usage cost reports.
    Automatically snapshots average_cost_price logic via the model's .cost property.
    """

    shop = serializers.PrimaryKeyRelatedField(
        queryset=Shop.objects.all(), required=False
    )
    recorded_by = serializers.HiddenField(default=serializers.CurrentUserDefault())

    # Nested writable items (POST) and readable items (GET)
    items = UsageItemSerializer(many=True, write_only=True)
    items_read = UsageItemSerializer(source="items", many=True, read_only=True)

    total_cost = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        help_text="Total usage cost (calculated from average cost at time of usage)",
    )

    class Meta:
        model = Usage
        fields = [
            "url",
            "id",
            "shop",
            "usage_date",
            "recorded_by",
            "total_cost",
            "note",
            "items",
            "items_read",
        ]
        extra_kwargs = {
            "url": {"view_name": "usage-detail"},
        }

    @transaction.atomic
    def create(self, validated_data):
        """
        Atomic creation of Usage + Items + Stock deduction.
        """
        items_data = validated_data.pop("items")
        request = self.context["request"]

        # Auto-populate user and shop
        validated_data["recorded_by"] = request.user
        if hasattr(request.user, "shop") and request.user.shop:
            validated_data["shop"] = request.user.shop

        usage = Usage.objects.create(**validated_data)

        # Create usage items (no unit_cost_price needed anymore)
        for item_data in items_data:
            UsageItem.objects.create(usage=usage, **item_data)

        # Update total and deduct stock
        usage.update_total()
        usage.deduct_stock(user=request.user)

        return usage