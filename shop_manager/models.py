from decimal import Decimal
import uuid
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from phonenumber_field.modelfields import PhoneNumberField  # type: ignore
from .utils import update_stock


# =============================================================================
# MODEL: Subscription Plan
# =============================================================================


class PlanType(models.TextChoices):
    BASIC = "Basic", "Basic"
    PRO = "Pro", "Pro"


class SubscriptionPlan(models.Model):
    """
    Defines subscription plans available to shop owners. Each plan has a price,
    user limits, and a trial period.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=100,
        unique=True,
        choices=PlanType.choices,
        help_text="The name of the subscription plan.",
    )
    price_per_month = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="The monthly price of the plan."
    )
    user_limit = models.IntegerField(
        help_text="Maximum number of users allowed on this plan per shop."
    )
    product_limit = models.IntegerField(
        help_text="Maximum number of products allowed in the shop."
    )
    shop_limit = models.IntegerField(
        help_text="Maximum number of shops allowed for a single user."
    )
    features = models.TextField(
        help_text="A detailed list of features available in this plan."
    )
    trial_days = models.IntegerField(
        default=30, help_text="The number of trial days for this plan."
    )

    def __str__(self):
        """
        Returns a string representation of the subscription plan name.
        """
        return self.name

    class Meta:
        indexes = [
            models.Index(fields=["price_per_month"]),
            models.Index(fields=["user_limit"]),
            models.Index(fields=["trial_days"]),
            models.Index(fields=["price_per_month", "name"]),
            models.Index(fields=["price_per_month", "user_limit"]),
            models.Index(fields=["price_per_month", "product_limit"]),
            models.Index(fields=["price_per_month", "shop_limit"]),
        ]


# =============================================================================
# MODEL: Shop
# =============================================================================


class Currency(models.TextChoices):
    USD = "USD", "United States Dollar"
    EUR = "EUR", "Euro"
    GBP = "GBP", "British Pound"
    KSH = "KSH", "Kenyan Shilling"
    TZS = "TZS", "Tanzanian Shilling"
    UGX = "UGX", "Ugandan Shilling"
    ZAR = "ZAR", "South African Rand"


class Shop(models.Model):
    """
    Represents a shop owned by a user with customizable settings.
    Each shop is tied to a user and has its own subscription plan.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="owned_shops",
        null=True,
        db_index=True,
    )
    name = models.CharField(max_length=255, help_text="The name of the shop.")
    description = models.TextField(
        blank=True, null=True, help_text="A brief description of the shop."
    )
    country = models.CharField(
        max_length=100, help_text="Country where the shop is located."
    )
    currency_code = models.CharField(
        max_length=10,
        choices=Currency.choices,
        help_text="Currency code used in the shop.",
    )
    logo = models.ImageField(
        upload_to="shop_logos/",
        blank=True,
        null=True,
        help_text="Upload the shop's logo image.",
    )
    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        help_text="The subscription plan assigned to the shop.",
    )
    is_active = models.BooleanField(
        default=True, help_text="Indicates if the shop is active."
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    def __str__(self):
        """
        Returns a string representation of the shop's name.
        """
        return self.name

    class Meta:
        indexes = [
            models.Index(fields=["owner"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["country"]),
            models.Index(fields=["subscription_plan"]),
        ]


# =============================================================================
# MODEL: Category
# =============================================================================


class Category(models.Model):
    """
    Product categories specific to a shop. Categories help organize products
    within a shop, making it easier for customers and shop owners to view products
    in specific segments or groups.
    """

    # Unique identifier for each category using UUID
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ForeignKey relationship to the Shop model.
    # Each category belongs to a specific shop.
    # The on_delete=models.CASCADE ensures that if a shop is deleted,
    # all its associated categories are deleted as well.
    shop = models.ForeignKey(
        "Shop", on_delete=models.CASCADE, related_name="categories"
    )

    # Name of the category (e.g., 'Electronics', 'Clothing', etc.)
    # This field is essential for identifying and organizing products.
    name = models.CharField(
        max_length=100, unique=True, help_text="The name of the product category."
    )

    # Optional field for a detailed description of the category.
    # Provides additional information about the category, if needed.
    description = models.TextField(
        blank=True, null=True, help_text="A brief description of the category."
    )

    # String representation of the category is its name.
    # This will be useful in the admin interface and other parts of the app.
    def __str__(self):
        """
        Returns a string representation of the category name.
        """
        return self.name

    # Adding indexes to frequently queried fields to improve performance
    class Meta:

        verbose_name_plural = "Categories"
        ordering = ["name"]
        # Index for the 'shop' field to speed up queries filtering by shop
        indexes = [
            # Index on 'shop' field for efficient queries filtering by shop
            models.Index(fields=["shop"]),
            # Index on 'name' field for fast searches by category name
            models.Index(fields=["name"]),
        ]


# =============================================================================
# MODEL: Supplier
# =============================================================================


class Supplier(models.Model):
    """
    Supplier information for product sourcing. This includes contact details
    and tax information for each supplier.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # ForeignKey to Shop: Every supplier belongs to a specific shop
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        help_text="The shop to which the supplier is linked.",
    )
    # Supplier's name
    name = models.CharField(max_length=255, help_text="The name of the supplier.")
    phone = PhoneNumberField(null=True, blank=True)
    address = models.TextField(
        blank=True, null=True, help_text="The supplier's physical address."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """
        Returns a string representation of the supplier name.
        """
        return self.name

    class Meta:
        # Add indexes for the fields that are frequently queried
        indexes = [
            # Index on the shop field to speed up lookups for suppliers per shop
            models.Index(fields=["shop"]),
            # Index on the name field to speed up searches by supplier name
            models.Index(fields=["name"]),
            # Index on the created_at field to efficiently filter suppliers by creation date
            models.Index(fields=["created_at"]),
        ]


class Brand(models.Model):
    """
    product brand/manufacturer information for
    better product organization and filtering
    """

    name = models.CharField(max_length=100, unique=True)
    country_of_origin = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class VehicleMake(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class VehicleModel(models.Model):
    make = models.ForeignKey(
        VehicleMake, on_delete=models.CASCADE, related_name="models"
    )
    name = models.CharField(max_length=100)
    year_start = models.PositiveIntegerField()
    year_end = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("make", "name", "year_start")

    def __str__(self):
        return (
            f"{self.make} {self.name} ({self.year_start}-{self.year_end or 'Present'})"
        )


# =============================================================================
# MODEL: Product
# =============================================================================
class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)

    category = models.ForeignKey(
        "Category", on_delete=models.PROTECT, related_name="products"
    )
    shop = models.ForeignKey("Shop", on_delete=models.CASCADE, related_name="products")

    # Compatibility – simple text field for MVP (can be normalized later)
    compatible_vehicles = models.ManyToManyField(
        VehicleModel, blank=True, help_text="Compatible vehicle models for this part"
    )

    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    # NEW: Weighted average cost
    average_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Weighted average cost price (auto-calculated from purchases)"
    )

    reorder_level = models.PositiveIntegerField(
        default=5, help_text="Stock level below which reorder is recommended"
    )

    # Stock is managed via Stock model – we keep reference here for convenience
    # But actual quantity should be read from Stock.current_quantity
    # (avoid data duplication – or use property / cached_property)

    is_active = models.BooleanField(default=True, db_index=True)
    is_discontinued = models.BooleanField(default=False, db_index=True)
    discontinued_reason = models.TextField(blank=True, null=True)
    discontinued_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="products_created",
    )
    updated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_products'
    )

    class Meta:
        indexes = [
            models.Index(fields=["shop", "name"]),
            models.Index(fields=["shop", "category", "is_active"]),
            models.Index(fields=["shop", "is_discontinued"]),
        ]
        ordering = ["name"]
        verbose_name = "Part"
        verbose_name_plural = "Parts"

    def __str__(self):
        return f"{self.name}"

    @property
    def current_stock(self):
        """Current stock level – read from related Stock model"""
        stock = self.stock.first()  # assuming OneToOne or first related
        return stock.quantity if stock else 0

    def mark_as_discontinued(self, reason: str, user):
        """Soft delete helper"""
        self.is_discontinued = True
        self.is_active = False
        self.discontinued_reason = reason
        self.discontinued_at = timezone.now()
        self.save(
            update_fields=[
                "is_discontinued",
                "is_active",
                "discontinued_reason",
                "discontinued_at",
            ]
        )


# =============================================================================
# MODEL: Stock
# =============================================================================


class Stock(models.Model):
    """
    Tracks the inventory level for each product in the shop.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # One-to-one relationship with Product: Each stock entry corresponds to a single product
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        help_text="The product this stock entry represents.",
    )

    # Quantity of the product in stock
    quantity = models.PositiveIntegerField(
        default=0, help_text="The current stock level of the product."
    )

    # Timestamp of the last update for the stock level (indexed for performance)
    last_updated = models.DateTimeField(
        auto_now=True, help_text="The date and time the stock was last updated."
    )

    reorder_level = models.PositiveIntegerField(null=True, blank=True, help_text="Shop-specific override")

    @property
    def effective_reorder_level(self):
        return self.reorder_level if self.reorder_level is not None else self.product.reorder_level
    
    
    @property
    def is_low_stock(self):
        return self.quantity <= self.effective_reorder_level

    def __str__(self):
        """
        Returns a string representation of the stock for the associated product.
        """
        return f"Stock for {self.product.name}"

    class Meta:
        # Add indexes on frequently queried fields for improved performance
        indexes = [
            models.Index(fields=["product"]),  # Index on the product field
            # Index on the last_updated field
            models.Index(fields=["last_updated"]),
            # Index on the last_updated field
            models.Index(fields=["quantity"]),
        ]


class StockTransaction(models.Model):
    """
    Immutable audit trail for every stock movement.
    Ensures traceability, reporting, and safe reversals.
    """

    TYPE_CHOICES = [
        ("purchase", "Stock In - Purchase"),
        ("sale", "Stock Out - Sale"),
        ("adjustment", "Manual Adjustment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock = models.ForeignKey(
        Stock,
        on_delete=models.PROTECT,  # Never delete transactions
        related_name="transactions",
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    quantity_change = models.IntegerField()  # + for in, - for out
    reason = models.CharField(max_length=255, blank=True)
    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. Purchase UUID, Sale UUID, or 'Initial stock'",
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["stock", "-created_at"]),
            models.Index(fields=["type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} {self.quantity_change:+d} → {self.stock.product.name}"

    @property
    def new_quantity(self):
        """Convenient property for reporting – quantity after this transaction"""
        # This is approximate – for exact, query ordered transactions
        return self.stock.quantity  # Current after all transactions


# =============================================================================
# MODEL: Purchase & PurchaseItem Models
# =============================================================================


class Purchase(models.Model):
    """
    Represents a purchase order from a supplier to restock products in the shop.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        help_text="The shop making the purchase.",
        related_name="purchases",
        db_index=True,
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        help_text="The supplier from whom the products are purchased.",
        related_name="purchases",
        db_index=True,
    )

    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="The total amount for the purchase."
    )

    payment_status = models.CharField(
        max_length=20,
        choices=[("Paid", "Paid"), ("Unpaid", "Unpaid"), ("Partial", "Partial")],
        help_text="The payment status of the purchase.",
        db_index=True,
    )

    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("Cash", "Cash"),
            ("Card", "Card"),
            ("M-Pesa", "M-Pesa"),
            ("Bank Transfer", "Bank Transfer"),
        ],
        help_text="The payment method used for the purchase.",
    )

    purchase_date = models.DateField(
        db_index=True, null=True, help_text="The date and time when the purchase was made."
    )

    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        help_text="The user who created the purchase.",
        related_name="created_purchases",
    )

    class Meta:
        indexes = [
            models.Index(fields=["shop", "supplier"]),
            models.Index(fields=["purchase_date"]),
            models.Index(fields=["payment_status"]),
        ]
        ordering = ["-purchase_date"]  # Recent purchases first

    def __str__(self):
        return f"Purchase from {self.supplier} on {self.purchase_date.strftime('%Y-%m-%d')}"

    def update_stock(self, user=None):
        """Apply stock increase for all items in this purchase"""
        for item in self.items.select_related('product').all():
            if item.quantity > 0:
                update_stock(
                    product=item.product,
                    quantity_change=item.quantity,
                    transaction_type="purchase",
                    reason=f"Purchase created/updated",
                    reference=str(self.id),
                    user=user,
                )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        # Only update stock on creation or when items change significantly
        # (for simplicity we do it every time – you can optimize later)
        if is_new and self.items.exists():
            self.update_stock(user=self.created_by)
    
    def clean(self):
        if not self.items.exists() and self.pk:
            raise ValidationError("A purchase must contain at least one item.")

    def update_total(self):
        """Call this after adding/removing items"""
        self.total_amount = sum(item.total_cost for item in self.items.all())
        self.save(update_fields=['total_amount'])


class PurchaseItem(models.Model):
    """
    Line items in a purchase, representing specific products purchased and their costs.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="items", db_index=True
    )

    product = models.ForeignKey(Product, on_delete=models.CASCADE, db_index=True)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The brand of the product in this specific purchase"
    )

    quantity = models.PositiveIntegerField()

    unit_cost_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True)

    def save(self, *args, **kwargs):
        if not self.unit_cost_price:
            self.unit_cost_price = self.product.cost_price
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost_price if self.unit_cost_price else Decimal('0.00')

    def __str__(self):
        return f"{self.quantity} x {self.product.name} @ {self.unit_cost_price}"

    class Meta:
        indexes = [
            models.Index(fields=["purchase"]),
            models.Index(fields=["product"]),
            models.Index(fields=["quantity"]),
        ]


# =============================================================================
# MODEL: Sale & Sale Items
# =============================================================================


class Sale(models.Model):
    """
    Represents a sale transaction, recording customer and payment information.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        help_text="The shop where the sale occurred.",
        db_index=True,
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="The total amount of the sale."
    )
    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.0,
        help_text="Discount applied to the sale.",
    )
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("Cash", "Cash"),
            ("Card", "Card"),
            ("M-Pesa", "M-Pesa"),
            ("Bank Transfer", "Bank Transfer"),
        ],
        help_text="The payment method used for the sale.",
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[("Paid", "Paid"), ("Unpaid", "Unpaid"), ("Partial", "Partial"), ("Pending", "Pending")],
        help_text="The payment status of the purchase.",
        db_index=True,
    )
    sold_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        help_text="The user who made the sale.",
    )
    sale_date = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="The date and time when the sale was made.", 
    )

    vehicle_make = models.ForeignKey(
        VehicleMake,
        on_delete=models.SET_NULL,      # or PROTECT / CASCADE — depending on business rule
        null=True,
        blank=True,
        related_name='sales',
        help_text="The make of vehicle the parts were sold for"
    )

    class Meta:
        indexes = [
            models.Index(fields=["sale_date"]),
            models.Index(fields=["payment_status"]),
            models.Index(fields=["shop"]),
        ]


class SaleItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name="items", db_index=True
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, db_index=True)
    quantity = models.PositiveIntegerField()
    unit_cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Snapshot of product's average_cost_price at time of sale"
    )  # frozen at sale time
    unit_selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Snapshot of selling price at time of sale (allows per-item overrides)"
    )  # frozen at sale time

    def save(self, *args, **kwargs):
        # Freeze average cost and selling price at the moment of sale (only if not already set)
        if not self.pk:  # on creation
            if self.unit_cost_price is None:
                self.unit_cost_price = getattr(self.product, 'average_cost_price', Decimal('0.00'))

            if self.unit_selling_price is None:
                self.unit_selling_price = self.product.selling_price or Decimal('0.00')

        super().save(*args, **kwargs)

    @property
    def profit_amount(self):
        cost = self.unit_cost_price or Decimal('0.00')
        return (self.unit_selling_price - cost) * self.quantity

    class Meta:
        indexes = [
            models.Index(fields=["sale", "product"]),
        ]

# =============================================================================
# MODEL: Expense
# =============================================================================


class Expense(models.Model):
    """
    Tracks various shop-related expenses like rent, utilities, maintenance, etc.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        help_text="The shop associated with the expense.",
    )
    title = models.CharField(max_length=255, help_text="A brief title for the expense.")
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="The total amount of the expense."
    )
    expense_type = models.CharField(
        max_length=50,
        choices=[
            ("rent", "Rent"),
            ("utility", "Utility"),
            ("maintenance", "Maintenance"),
            ("wages", "Wages"),
            ("misc", "Miscellaneous"),
        ],
        help_text="The category of the expense.",
    )
    incurred_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        help_text="The user who incurred the expense.",
    )
    date = models.DateField(
        db_index=True, help_text="The date when the expense occurred."
    )


class Returns(models.Model):
    """Warranty/returns tracking"""

    sale_item = models.ForeignKey(
        SaleItem, on_delete=models.CASCADE, related_name="returns"
    )
    return_date = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(
        max_length=200,
        choices=[("defect", "Defect"), ("wrong_fit", "Wrong Fit"), ("other", "Other")],
    )
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2)
    resolved = models.BooleanField(default=False)

    def __str__(self):
        return f"Return for {self.sale_item.product.name} - {self.reason}"


# =============================================================================
# MODEL: Offline Sync Log
# =============================================================================


class OfflineSyncLog(models.Model):
    """
    Tracks synchronization attempts for offline mode. Each log stores the status of the sync process.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        help_text="The shop for which sync logs are recorded.",
    )
    sync_status = models.CharField(
        max_length=20,
        choices=[("Success", "Success"), ("Failure", "Failure")],
        help_text="The status of the sync attempt.",
    )
    sync_date = models.DateTimeField(
        auto_now_add=True, help_text="The date and time when the sync occurred."
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Any error message returned during the sync process.",
    )


# =============================================================================
# END OF MODELS
# =============================================================================
