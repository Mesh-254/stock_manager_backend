from rest_framework import serializers
from shop_manager.signals import recalculate_sale_total
from .models import *
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import ValidationError
from decimal import Decimal
from django.contrib.auth import get_user_model


User = get_user_model()


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "country_of_origin"]
        read_only_fields = ["id"]


# =============================================================================
# SubscriptionPlan Serializer
# =============================================================================


class SubscriptionPlanSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the SubscriptionPlan model using HyperlinkedModelSerializer.
    Includes related metadata.
    """

    # You can add other relations here if needed, for example, linking to a 'Shop' model
    # shop = serializers.HyperlinkedRelatedField(view_name="shop-detail", read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = [
            "url",  # Hyperlinked reference to this SubscriptionPlan instance
            "id",
            "name",
            "price_per_month",
            "user_limit",
            "product_limit",
            "shop_limit",
            "features",
            "trial_days",
        ]
        read_only_fields = ["id", "is_active"]  # Read-only fields

        extra_kwargs = {
            # Assuming 'subscriptionplan-detail' is your URL pattern name
            "url": {"view_name": "subscriptionplan-detail"},
        }


# =============================================================================
# Shop Serializer
# =============================================================================


class ShopSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the Shop model. This serializer converts Shop instances to JSON
    and handles incoming data for creating or updating Shop objects.

    It includes fields for shop details, subscription plan, and owner.
    The 'logo' field is validated to ensure it is an image and meets the required formats.
    """

    # Linking to the owner and subscription plan via HyperlinkedRelatedField
    owner = serializers.HyperlinkedRelatedField(
        queryset=User.objects.all(),
        view_name="user-detail",  # Ensure there's a URL pattern named 'user-detail' for User
    )
    subscription_plan = serializers.HyperlinkedRelatedField(
        queryset=SubscriptionPlan.objects.all(),
        # Ensure there's a URL pattern named 'subscriptionplan-detail' for SubscriptionPlan
        view_name="subscriptionplan-detail",
    )

    # Handle image validation for the 'logo' field
    logo = serializers.ImageField(
        required=False,  # Not mandatory, it can be left blank
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"])],
        help_text="Upload the shop's logo. Only .jpg, .jpeg, or .png formats are accepted.",
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
            "subscription_plan",
            "is_active",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            # Define the URL name for Shop detail
            "url": {"view_name": "shop-detail"},
        }


# =============================================================================
# Category Serializer
# =============================================================================


class CategorySerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the Category model. This serializer converts Category instances to JSON
    and handles incoming data for creating or updating Category objects.
    It represents the relationship between Category and Shop using hyperlinks.
    """

    # Use a hyperlink to represent the related shop, rather than nesting all shop data
    shop = serializers.HyperlinkedRelatedField(
        queryset=Shop.objects.all(),
        view_name="shop-detail",  # Ensure the URL pattern for shop-detail is defined
        help_text="URL of the shop to which this category belongs.",
    )

    class Meta:
        model = Category
        fields = ["url", "id", "shop", "name", "description"]
        extra_kwargs = {
            # URL for accessing category details
            "url": {"view_name": "category-detail"},
            # URL for accessing shop details
            "shop": {"view_name": "shop-detail"},
        }

    def validate_name(self, value):
        """
        Custom validator to ensure the name field is not empty and has a valid length.
        """
        if not value:
            raise serializers.ValidationError("Category name cannot be empty.")
        if len(value) > 100:
            raise serializers.ValidationError(
                "Category name is too long. Maximum length is 100 characters."
            )
        return value

    def validate_description(self, value):
        """
        Custom validator for description to ensure the description does not exceed 500 characters.
        """
        if value and len(value) > 500:
            raise serializers.ValidationError(
                "Description is too long. Maximum length is 500 characters."
            )
        return value

    def create(self, validated_data):
        """
        Override the create method to add custom logic when a category is created.
        """
        category = Category.objects.create(**validated_data)
        return category

    def update(self, instance, validated_data):
        """
        Override the update method to add custom logic when a category is updated.
        """
        instance.name = validated_data.get("name", instance.name)
        instance.description = validated_data.get("description", instance.description)
        instance.shop = validated_data.get("shop", instance.shop)
        instance.save()
        return instance


# =============================================================================
# Supplier Serializer
# =============================================================================


class SupplierSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the Supplier model. This serializer converts Supplier instances to JSON
    and handles incoming data for creating or updating Supplier objects.
    It represents the relationship between Supplier and Shop using hyperlinks.
    """

    # Use a hyperlink to represent the related shop, rather than nesting all shop data
    shop = serializers.HyperlinkedRelatedField(
        queryset=Shop.objects.all(),
        view_name="shop-detail",  # Ensure the URL pattern for shop-detail is defined
        help_text="URL of the shop to which this supplier belongs.",
    )

    class Meta:
        model = Supplier
        fields = ["url", "id", "shop", "name", "phone", "address", "created_at"]
        extra_kwargs = {
            # URL for accessing supplier details
            "url": {"view_name": "supplier-detail"},
            # URL for accessing shop details
            "shop": {"view_name": "shop-detail"},
        }

    def validate_phone(self, value):
        """
        Custom validator for the phone number to ensure it's in a valid format.
        For simplicity, let's assume it should contain only digits and be 10-15 characters long.
        """

        if len(value) < 10 or len(value) > 15:
            raise serializers.ValidationError(
                "Phone number should be between 10 and 15 digits."
            )
        return value

    def create(self, validated_data):
        """
        Override the create method to add custom logic when a supplier is created.
        """
        supplier = Supplier.objects.create(**validated_data)
        return supplier

    def update(self, instance, validated_data):
        """
        Override the update method to add custom logic when a supplier is updated.
        """
        instance.name = validated_data.get("name", instance.name)
        instance.phone = validated_data.get("phone", instance.phone)
        instance.address = validated_data.get("address", instance.address)
        instance.shop = validated_data.get("shop", instance.shop)
        instance.save()
        return instance


# =============================================================================
# Product Serializer
# =============================================================================


class ProductListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    current_stock = serializers.IntegerField(
        source="stock.quantity", read_only=True, default=0
    )
    needs_reorder = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "category",
            "brand",
            "cost_price",
            "selling_price",
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
        stock = getattr(obj, "stock", None)
        if stock and hasattr(stock, "quantity"):
            return stock.quantity <= obj.reorder_level
        return False


# ────────────────────────────────────────────────
#  DETAIL serializer (single object view)
# ────────────────────────────────────────────────
class ProductDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    supplier = SupplierSerializer(read_only=True)
    current_stock = serializers.IntegerField(
        source="stock.quantity", read_only=True, default=0
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
            "shop",  # usually set automatically
        ]


# ────────────────────────────────────────────────
#  CREATE & UPDATE serializer
# ────────────────────────────────────────────────
class ProductWriteSerializer(serializers.ModelSerializer):
    """
    Used for both create and update.
    Note: stock quantity is only accepted on creation.
    After creation, stock should be managed via purchase/sale/adjustment.
    """

    initial_stock = serializers.IntegerField(
        write_only=True,
        required=False,
        default=0,
        min_value=0,
        help_text="Initial stock quantity (only used on creation)",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "description",
            "category",
            "brand",
            "supplier",
            "compatible_vehicles",
            "cost_price",
            "selling_price",
            "reorder_level",
            "initial_stock",
        ]

    def create(self, validated_data):
        initial_stock = validated_data.pop("initial_stock", 0)
        user = self.context["request"].user

        product = Product.objects.create(
            **validated_data,
            shop=user.shop if hasattr(user, "shop") else None,
            created_by=user
        )

        if initial_stock > 0:
            Stock.objects.create(
                product=product,
                quantity=initial_stock,
                # you may want to create a StockTransaction here too
            )

        return product

    def update(self, instance, validated_data):
        # Prevent changing stock quantity directly
        validated_data.pop("initial_stock", None)
        return super().update(instance, validated_data)


# =============================================================================
# Stock Serializer
# =============================================================================
class StockTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer for stock transaction history (read-only for most users).
    Includes product name and creator for easy display.
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
            "reference_id",
            "created_by",
            "created_by_name",
            "created_at",
            "product_id",
            "product_name",
        ]
        read_only_fields = fields  # All read-only – transactions are immutable


class StockSerializer(serializers.HyperlinkedModelSerializer):
    """
    Serializer for the Stock model. This serializer converts Stock instances to JSON
    and handles incoming data for creating or updating Stock objects.
    It represents the relationship between Stock and Product using hyperlinks.
    """

    # Hyperlink for the related Product
    product = serializers.HyperlinkedRelatedField(
        queryset=Product.objects.all(),
        view_name="product-detail",  # Ensure this URL pattern exists for product details
        help_text="URL of the product associated with this stock.",
    )

    low_stock = serializers.BooleanField(
        source="is_low_stock", read_only=True
    )  # Add property in Stock model

    class Meta:
        model = Stock
        fields = ["url", "id", "product", "quantity", "last_updated"]
        extra_kwargs = {
            # URL for accessing stock details
            "url": {"view_name": "stock-detail"},
            # URL for accessing product details
            "product": {"view_name": "product-detail"},
        }

    def validate_product(self, value):
        """
        Ensure the product stock is not duplicated and product exists in the database.
        """
        try:
            # If updating, self.instance will be the Stock object being updated

            if self.instance:
                if self.instance.product == value:
                    return value
            # Check if the product already exists in stock
            if Stock.objects.filter(product=value).exists():
                raise serializers.ValidationError("Product stock already exists.")
            Product.objects.get(id=value.id)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product does not exist in the database.")
        return value

    def validate_quantity(self, value):
        """
        Ensure the quantity is non-negative.
        """
        if value < 0:
            raise serializers.ValidationError("Quantity cannot be negative.")
        return value

    def create(self, validated_data):
        """
        Override the create method to add custom logic when creating a stock entry.
        """
        stock = Stock.objects.create(**validated_data)
        return stock

    def update(self, instance, validated_data):
        """
        Override the update method to add custom logic when updating a stock entry.
        """
        instance.quantity = validated_data.get("quantity", instance.quantity)
        instance.product = validated_data.get("product", instance.product)
        instance.save()
        return instance


# =============================================================================
# PUrchaseItem & Purchase Serializer
# =============================================================================


class PurchaseItemSerializer(serializers.HyperlinkedModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    purchase = serializers.HyperlinkedRelatedField(
        view_name="purchase-detail", read_only=True
    )

    brand = serializers.PrimaryKeyRelatedField(  # Explicitly add to use PK (accepts ID)
        queryset=Brand.objects.all(), allow_null=True
    )

    total_cost = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchaseItem
        fields = [
            "url",
            "product",
            "quantity",
            "brand",
            "unit_cost_price",
            "purchase",
            "total_cost",
        ]
        extra_kwargs = {"url": {"view_name": "purchaseitem-detail"}}

    def get_total_cost(self, obj):
        return (
            obj.quantity * obj.unit_cost_price
            if obj.unit_cost_price
            else Decimal("0.00")
        )

    def validate(self, data):
        if data["quantity"] <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        if data.get("unit_cost_price", 0) < 0:
            raise serializers.ValidationError("Unit cost cannot be negative")
        return data


class PurchaseSerializer(serializers.HyperlinkedModelSerializer):

    shop = serializers.PrimaryKeyRelatedField(  # Change to PK (accepts ID)
        queryset=Shop.objects.all(),
        required=False,  # Make optional; view will auto-set for ShopAdmins
    )
    total_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    supplier = serializers.PrimaryKeyRelatedField(  # Change to PK (accepts ID)
        queryset=Supplier.objects.all(), allow_null=True
    )

    created_by = serializers.HiddenField(default=serializers.CurrentUserDefault())

    # Split: items_read for GET, items for POST
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
            "created_by",  # optional: hide or set via user
            "items",
            "items_read",
        ]
        read_only_fields = ["id", "total_amount", "created_by"]
        extra_kwargs = {
            "url": {"view_name": "purchase-detail"},
        }

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        request = self.context["request"]

        # Auto-set created_by and shop
        validated_data["created_by"] = request.user
        if request.user.role == "ShopAdmin":
            validated_data["shop"] = request.user.shop

        purchase = Purchase.objects.create(**validated_data)

        for item_data in items_data:
            PurchaseItem.objects.create(purchase=purchase, **item_data)

        return purchase


# =============================================================================
# SaleItem & Sale Serializer
# =============================================================================


class SaleItemSerializer(serializers.HyperlinkedModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    sale = serializers.HyperlinkedRelatedField(view_name="sale-detail", read_only=True)
    unit_cost_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = SaleItem
        fields = [
            "url",
            "id",
            "sale",
            "product",
            "quantity",
            "unit_cost_price",
            "unit_selling_price",
        ]


class SaleSerializer(serializers.HyperlinkedModelSerializer):
    items = SaleItemSerializer(many=True)
    total_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    shop = serializers.PrimaryKeyRelatedField(
        queryset=Shop.objects.all(), required=False
    )
    sold_by = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Sale
        fields = [
            "url",
            "id",
            "shop",
            "total_amount",
            "discount",
            "payment_method",
            "payment_status",
            "sold_by",
            "sale_date",
            "items",
        ]

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        request = self.context['request']

        validated_data['sold_by'] = request.user
        if hasattr(request.user, 'shop') and request.user.shop:
            validated_data['shop'] = request.user.shop
        else:
            raise ValidationError("User must be associated with a shop to create a sale.")

        sale = Sale.objects.create(**validated_data, total_amount=Decimal('0.00'))

        for item_data in items_data:
            product = item_data['product']
            item_data['unit_cost_price'] = product.average_cost_price or Decimal('0.00')  # <-- Snapshot average
            SaleItem.objects.create(sale=sale, **item_data)

        recalculate_sale_total(sale)
        return sale
