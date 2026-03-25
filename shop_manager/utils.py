"""
Stock Utility Functions

Central helper for all stock movements (purchase, usage, adjustment).
Ensures atomicity, prevents negative stock (except reversals), and always creates an audit trail via StockTransaction.
"""

from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal


@transaction.atomic
def update_stock(
    product,
    quantity_change: Decimal,
    transaction_type="unknown",
    reason="",
    reference="",
    user=None,
):
    """
    Update stock quantity + create immutable audit transaction.

    Raises ValidationError on negative stock (unless it's a reversal).
    Uses select_for_update() to prevent race conditions in concurrent requests.
    """
    from .models import Stock, StockTransaction

    # Get or create stock record (locked for update)
    stock, _ = Stock.objects.select_for_update().get_or_create(
        product=product, defaults={"quantity": Decimal("0.00")}
    )

    new_quantity = stock.quantity + quantity_change

    # Allow negative only for explicit reversals/deletes
    is_reversal = any(
        keyword in str(transaction_type).lower() + str(reason).lower()
        for keyword in ["reversal", "delete", "deleted", "remove", "correction"]
    )

    if quantity_change < 0 and new_quantity < 0 and not is_reversal:
        raise ValidationError(
            f"Cannot reduce stock below zero for {product.name}. "
            f"Current: {stock.quantity}, attempted change: {quantity_change}"
        )

    stock.quantity = new_quantity
    stock.save(update_fields=["quantity"])

    StockTransaction.objects.create(
        stock=stock,
        type=transaction_type,
        quantity_change=quantity_change,
        reason=reason,
        reference=reference,
        created_by=user,
    )

    return stock
