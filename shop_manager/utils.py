"""
Stock Utility Functions

Central helper for all stock movements with proper user-friendly error handling.
"""

from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError



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
    Update stock quantity + create audit transaction.
    Raises user-friendly ValidationError when stock would go negative.
    """
    from .models import Stock, StockTransaction

    # Get or create stock record (locked for update)
    stock, _ = Stock.objects.select_for_update().get_or_create(
        product=product, defaults={"quantity": Decimal("0.00")}
    )

    new_quantity = stock.quantity + quantity_change

    # === PREVENT NEGATIVE STOCK ===
    if quantity_change < 0 and new_quantity < 0:
        raise DjangoValidationError(
            f"Cannot reduce stock below zero for {product.name}. "
            f"Current stock: {stock.quantity:.3f}, attempted usage: {abs(quantity_change):.3f}"
        )

    stock.quantity = new_quantity
    stock.save(update_fields=["quantity"])

    # Create audit trail
    StockTransaction.objects.create(
        stock=stock,
        type=transaction_type,
        quantity_change=quantity_change,
        reason=reason,
        reference=reference,
        created_by=user,
    )

    return stock
