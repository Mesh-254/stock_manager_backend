"""
Shop Management Models for Secondary School Inventory System

This module defines all core models for managing a school shop/inventory system.
It supports:
- Multi-shop (multi-tenant) architecture
- Different units of measurement (books in pieces, maize in kg/bags, etc.)
- Accurate stock tracking with weighted average costing
- Daily usage/consumption recording (instead of traditional sales)
- Purchase management with supplier tracking
- Expense tracking
- Full audit trail via StockTransaction

Designed for performance with proper indexes for common reports:
- Daily/Monthly Usage Reports
- Purchase vs Usage comparison
- Stock valuation
- Low-stock alerts
"""

from decimal import Decimal
import uuid

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from phonenumber_field.modelfields import PhoneNumberField

# Local import
from .utils import update_stock  # Handles quantity change + creates StockTransaction


# =============================================================================
# UNIT CHOICES
# =============================================================================
UNIT_CHOICES = [
    ("pieces", "Pieces"),  # For books, exercise books, pens, etc.
    ("kg", "Kilograms"),  # For maize, rice, sugar, etc.
    ("bags", "Bags"),  # For 50kg or 90kg sacks of cereals
    ("liters", "Liters"),  # For cooking oil, milk, etc.
    ("boxes", "Boxes"),  # For packed items like chalk boxes
]
"""
Unit handling strategy:
- All quantity fields use DecimalField with 3 decimal places.
- Books → whole numbers (e.g., 45.000 pieces)
- Maize → fractional values (e.g., 125.500 kg or 3.000 bags)
- This allows flexible and accurate tracking for a school environment.
"""


# =============================================================================
# CURRENCY CHOICES
# =============================================================================
class Currency(models.TextChoices):
    """
    Currency options supported by the system.
    Used by Shop to define the default currency for all financial calculations.
    """

    USD = "USD", "United States Dollar"
    EUR = "EUR", "Euro"
    GBP = "GBP", "British Pound"
    KSH = "KSH", "Kenyan Shilling"
    TZS = "TZS", "Tanzanian Shilling"
    UGX = "UGX", "Ugandan Shilling"
    ZAR = "ZAR", "South African Rand"


# =============================================================================
# MODEL: Shop
# =============================================================================
class Shop(models.Model):
    """
    Represents a school shop or department store.
    Each shop belongs to one owner (usually a school admin) and operates independently.
    Supports multi-tenancy so one installation can serve multiple schools.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique identifier for the shop",
    )
    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="owned_shops",
        null=True,
        db_index=True,
        help_text="The user who owns/manages this shop",
    )
    name = models.CharField(
        max_length=255,
        help_text="Name of the shop (e.g., 'Main School Canteen', 'Bookshop')",
    )
    description = models.TextField(
        blank=True, null=True, help_text="Optional description of the shop"
    )
    country = models.CharField(
        max_length=100, help_text="Country where the shop is located"
    )
    currency_code = models.CharField(
        max_length=10,
        choices=Currency.choices,
        help_text="Default currency used for all transactions in this shop",
    )
    logo = models.ImageField(
        upload_to="shop_logos/", blank=True, null=True, help_text="Shop logo (optional)"
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether the shop is currently active"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Date and time when the shop was created",
    )
    updated_at = models.DateTimeField(
        auto_now=True, db_index=True, help_text="Last time the shop record was modified"
    )

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
        ]


# =============================================================================
# MODEL: Category
# =============================================================================
class Category(models.Model):
    """
    Product categories specific to each shop.
    Example: 'Stationery', 'Foodstuff', 'Cleaning Materials', 'Textbooks'
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name="categories",
        help_text="The shop this category belongs to",
    )
    name = models.CharField(
        max_length=100, help_text="Category name (must be unique within the same shop)"
    )
    description = models.TextField(
        blank=True, null=True, help_text="Optional detailed description of the category"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]
        unique_together = [
            ("shop", "name")
        ]  # Important: category name is unique per shop
        indexes = [
            models.Index(fields=["shop"]),
            models.Index(fields=["name"]),
            models.Index(fields=["shop", "name"]),  # Optimized for common lookups
        ]


# =============================================================================
# MODEL: Supplier
# =============================================================================
class Supplier(models.Model):
    """
    Suppliers from whom the school shop purchases stock.
    Used for purchase tracking and reporting.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name="suppliers",
        help_text="The shop this supplier is linked to",
    )
    name = models.CharField(
        max_length=255, help_text="Supplier's full name or company name"
    )
    phone = PhoneNumberField(
        null=True, blank=True, help_text="Contact phone number of the supplier"
    )
    address = models.TextField(
        blank=True, null=True, help_text="Physical or postal address of the supplier"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            models.Index(fields=["shop"]),
            models.Index(fields=["name"]),
            models.Index(fields=["created_at"]),
        ]


# =============================================================================
# MODEL: Product
# =============================================================================
class Product(models.Model):
    """
    Core product model for school inventory.
    Supports different units and maintains weighted average cost for accurate
    usage cost calculation (very important for school financial reports).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        help_text="Category this product belongs to",
    )
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="products")

    # Unit handling for school context
    unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        default="pieces",
        help_text="Unit of measurement (pieces for books, kg/bags for food items)",
    )

    cost_price = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Latest purchase price per unit"
    )
    average_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Weighted average cost used for usage costing and stock valuation",
    )

    reorder_level = models.PositiveIntegerField(
        default=5, help_text="Minimum stock level before reorder alert is triggered"
    )

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
        help_text="User who created this product",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["shop", "name"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_unit_display()})"

    @property
    def current_stock(self):
        """
        Returns current stock quantity for this product.
        Uses related Stock model (OneToOne).
        """
        stock = getattr(self, "stock", None)
        return stock.quantity if stock else Decimal("0.00")


# =============================================================================
# MODEL: Stock
# =============================================================================
class Stock(models.Model):
    """
    One-to-one relationship with Product to track current stock level.
    Separated from Product to keep product metadata clean.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.OneToOneField(
        Product, on_delete=models.CASCADE, related_name="stock"
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.00"),
        help_text="Current stock quantity (supports decimals for kg, liters, etc.)",
    )
    last_updated = models.DateTimeField(auto_now=True)

    @property
    def is_low_stock(self):
        """Check if stock is at or below reorder level"""
        return self.quantity <= Decimal(self.product.reorder_level)

    def __str__(self):
        return f"Stock for {self.product.name}"

    class Meta:
        indexes = [
            models.Index(fields=["product"]),
            models.Index(fields=["last_updated"]),
            models.Index(fields=["quantity"]),
        ]


# =============================================================================
# MODEL: StockTransaction
# =============================================================================
class StockTransaction(models.Model):
    """
    Audit trail for all stock movements (purchases, usage, manual adjustments).
    This enables full traceability and historical reporting.
    """

    TYPE_CHOICES = [
        ("purchase", "Stock In - Purchase"),
        ("usage", "Stock Out - Usage"),
        ("adjustment", "Manual Adjustment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock = models.ForeignKey(
        Stock, on_delete=models.PROTECT, related_name="transactions"
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        db_index=True,
        help_text="Type of stock movement",
    )
    quantity_change = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        help_text="Positive for stock in, negative for stock out",
    )
    reason = models.CharField(max_length=255, blank=True)
    reference = models.CharField(
        max_length=100, blank=True, help_text="Reference to Purchase ID, Usage ID, etc."
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True
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
        return f"{self.get_type_display()} {self.quantity_change:+.3f} → {self.stock.product.name}"


# =============================================================================
# MODEL: Purchase & PurchaseItem
# =============================================================================
class Purchase(models.Model):
    """
    Records stock purchases from suppliers.
    Automatically updates stock quantity and recalculates weighted average cost.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop, on_delete=models.CASCADE, related_name="purchases", db_index=True
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        related_name="purchases",
        db_index=True,
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total cost of this purchase (calculated from items)",
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[("Paid", "Paid"), ("Unpaid", "Unpaid"), ("Partial", "Partial")],
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
    )
    purchase_date = models.DateField(db_index=True, null=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["shop", "supplier"]),
            models.Index(fields=["purchase_date"]),
            models.Index(fields=["payment_status"]),
        ]
        ordering = ["-purchase_date"]

    def __str__(self):
        return f"Purchase from {self.supplier} on {self.purchase_date}"

    def update_total(self):
        """Recalculate and save total_amount from all purchase items"""
        self.total_amount = sum(item.total_cost for item in self.items.all())
        self.save(update_fields=["total_amount"])

    def update_stock(self, user=None):
        """
        For each item:
         1. Update product's weighted average_cost_price
         2. Increase stock quantity via update_stock utility
        """
        for item in self.items.select_related("product").all():
            if item.quantity <= 0:
                continue

            product = item.product
            stock = getattr(product, "stock", None)
            if not stock:
                continue

            # Calculate new weighted average cost BEFORE updating quantity
            old_qty = stock.quantity
            old_avg = product.average_cost_price or Decimal("0.00")
            add_qty = item.quantity
            add_cost = item.unit_cost_price or product.cost_price

            if old_qty + add_qty > 0:
                new_avg = (old_qty * old_avg + add_qty * add_cost) / (old_qty + add_qty)
                product.average_cost_price = new_avg
                product.save(update_fields=["average_cost_price"])

            # Update actual stock quantity + create transaction log
            update_stock(
                product=product,
                quantity_change=item.quantity,
                transaction_type="purchase",
                reason=f"Purchase {self.id}",
                reference=str(self.id),
                user=user,
            )


class PurchaseItem(models.Model):
    """
    Individual line item in a Purchase.
    """

    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        help_text="Cost per unit at time of purchase",
    )

    def save(self, *args, **kwargs):
        """Auto-fill unit_cost_price from product if not provided"""
        if not self.unit_cost_price:
            self.unit_cost_price = self.product.cost_price
        super().save(*args, **kwargs)

    @property
    def total_cost(self):
        """Total cost for this line item"""
        return (
            self.quantity * self.unit_cost_price
            if self.unit_cost_price
            else Decimal("0.00")
        )

    class Meta:
        indexes = [
            models.Index(fields=["purchase"]),
            models.Index(fields=["product"]),
        ]


# =============================================================================
# MODEL: Usage & UsageItem  (Replaces traditional Sales)
# =============================================================================
class Usage(models.Model):
    """
    Daily or batch consumption/usage of items in the school.
    Example: Books issued to students, maize used in kitchen on a particular day.
    This model is central to generating accurate usage cost reports.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="usages")
    usage_date = models.DateField(
        default=timezone.now,
        db_index=True,
        help_text="Date when this usage/consumption occurred",
    )
    recorded_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True
    )
    total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total cost of items used (based on average_cost_price)",
    )
    note = models.TextField(
        blank=True, null=True, help_text="Optional notes about this usage batch"
    )

    class Meta:
        ordering = ["-usage_date"]
        indexes = [
            models.Index(
                fields=["shop", "usage_date"]
            ),  # Critical for monthly/period reports
        ]

    def update_total(self):
        """Recalculate total_cost from all usage items"""
        self.total_cost = sum(item.cost for item in self.items.all())
        self.save(update_fields=["total_cost"])

    def deduct_stock(self, user=None):
        """
        Deduct used quantities from stock and create usage transactions.
        Called after Usage creation.
        """
        for item in self.items.select_related("product").all():
            if item.quantity > 0:
                update_stock(
                    product=item.product,
                    quantity_change=-item.quantity,  # Negative = stock out
                    transaction_type="usage",
                    reason=f"Usage {self.id}",
                    reference=str(self.id),
                    user=user,
                )


class UsageItem(models.Model):
    """
    Individual item used in a Usage record.
    Stores a snapshot of average_cost_price at the time of usage for accurate reporting.
    """

    usage = models.ForeignKey(Usage, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Snapshot of product's average_cost_price at time of usage",
    )

    @property
    def cost(self):
        """Cost of this usage item (quantity × average cost at time of usage)"""
        return self.quantity * self.unit_cost_price

    class Meta:
        unique_together = (
            "usage",
            "product",
        )  # Prevent duplicate products in one usage


# =============================================================================
# MODEL: Expense
# =============================================================================
class Expense(models.Model):
    """
    Non-stock expenses such as rent, wages, utilities, etc.
    Useful for overall school shop profitability reports.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="expenses")
    title = models.CharField(
        max_length=255, help_text="Short description of the expense"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_type = models.CharField(
        max_length=50,
        choices=[
            ("rent", "Rent"),
            ("utility", "Utility"),
            ("maintenance", "Maintenance"),
            ("wages", "Wages"),
            ("misc", "Miscellaneous"),
        ],
    )
    incurred_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True
    )
    date = models.DateField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=["shop", "date"])]


# =============================================================================
# MODEL: OfflineSyncLog
# =============================================================================
class OfflineSyncLog(models.Model):
    """
    Logs synchronization attempts when using the system in offline mode
    (e.g., mobile app syncing with server).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        Shop, on_delete=models.CASCADE, help_text="Shop this sync log belongs to"
    )
    sync_status = models.CharField(
        max_length=20, choices=[("Success", "Success"), ("Failure", "Failure")]
    )
    sync_date = models.DateTimeField(auto_now_add=True)
    error_message = models.TextField(
        blank=True,
        null=True,
        help_text="Details of any error that occurred during sync",
    )
