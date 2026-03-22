from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal
from .models import Product, Purchase, PurchaseItem, Sale, SaleItem, Stock
from .utils import update_stock


# =============================================================================
# Ensure Stock record with quantity=0 exists when Product is created
# =============================================================================
@receiver(post_save, sender=Product)
def create_initial_stock(sender, instance, created, **kwargs):
    if created:
        Stock.objects.get_or_create(product=instance, defaults={"quantity": 0})


# =============================================================================
# Purchase total recalculation (unchanged but kept for clarity)
# =============================================================================
def recalculate_purchase_total(purchase):
    """Atomic total recalculation"""
    with transaction.atomic():
        total = purchase.items.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("quantity") * F("unit_cost_price"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"] or Decimal("0.00")

        if purchase.total_amount != total:
            purchase.total_amount = total
            purchase.save(update_fields=["total_amount"])


# =============================================================================
# Capture old quantity before save
# =============================================================================
@receiver(pre_save, sender=PurchaseItem)
def purchase_item_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = PurchaseItem.objects.only("quantity").get(pk=instance.pk)
            instance._old_quantity = old.quantity
        except PurchaseItem.DoesNotExist:
            instance._old_quantity = 0
    else:
        instance._old_quantity = 0


# =============================================================================
# Handle PurchaseItem create & update → adjust stock by diff
# =============================================================================
@receiver(post_save, sender=PurchaseItem)
def handle_purchase_item_change(sender, instance, created, **kwargs):
    old_qty = getattr(instance, "_old_quantity", 0)
    diff = instance.quantity - old_qty

    if diff != 0 and instance.product_id:
        transaction_type = "purchase" if diff > 0 else "purchase_reversal"
        reason = f"Purchase {'added' if created else 'updated'} (Purchase {instance.purchase.id})"
        reference = str(instance.purchase.id)
        user = (
            instance.purchase.created_by
            if hasattr(instance.purchase, "created_by")
            else None
        )

        update_stock(
            product=instance.product,
            quantity_change=diff,
            transaction_type=transaction_type,
            reason=reason,
            reference=reference,
            user=user,
        )

    # Always recalculate purchase total
    if instance.purchase:
        recalculate_purchase_total(instance.purchase)

    # Clean up temporary attribute
    if hasattr(instance, "_old_quantity"):
        del instance._old_quantity


# =============================================================================
# Handle Purchase delete  → adjust stock by diff
# =============================================================================
@receiver(pre_delete, sender=Purchase)
def handle_purchase_delete(sender, instance, **kwargs):
    """
    Reverse stock BEFORE items are deleted.
    This runs once per purchase — safe and atomic.
    """
    for item in instance.items.all():
        if item.quantity > 0 and item.product_id:
            update_stock(
                product=item.product,
                quantity_change=-item.quantity,
                transaction_type="purchase_reversal",
                reason=f"Purchase deleted (ID {instance.id})",
                reference=str(instance.id),
                user=None,  # or get from context if middleware sets it
            )


# =============================================================================
# Handle PurchaseItem delete  → adjust stock by diff
# =============================================================================


@receiver(post_delete, sender=PurchaseItem)
def handle_purchase_item_delete(sender, instance, **kwargs):
    """
    Only recalculate total if purchase still exists.
    Do NOT reverse stock here — already done in purchase pre_delete.
    """
    if (
        instance.purchase_id
        and Purchase.objects.filter(id=instance.purchase_id).exists()
    ):
        recalculate_purchase_total(instance.purchase)


@receiver(pre_delete, sender=Purchase)
def mark_items_for_bulk_delete(sender, instance, **kwargs):
    for item in instance.items.all():
        item._deleting_with_purchase = True


# =============================================================================
# Handle Purchase Average Cost Recalculation (if needed)
# =============================================================================


@transaction.atomic
def recalculate_average_cost(product):
    agg = PurchaseItem.objects.filter(product=product).aggregate(
        total_quantity=Sum("quantity"),
        total_cost=Sum(
            ExpressionWrapper(
                F("quantity") * F("unit_cost_price"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            )
        ),
    )
    total_qty = agg["total_quantity"] or Decimal("0")
    total_cost = agg["total_cost"] or Decimal("0.00")

    new_avg = (
        (total_cost / total_qty).quantize(Decimal("0.01"))
        if total_qty > 0
        else Decimal("0.00")
    )

    if getattr(product, "average_cost_price", None) != new_avg:
        product.average_cost_price = new_avg
        product.save(update_fields=["average_cost_price"])
    return new_avg


# =============================================================================
# Handle Purchase Average Cost Recalculation Signals
# =============================================================================


@receiver(post_save, sender=PurchaseItem)
@receiver(post_delete, sender=PurchaseItem)
def update_average_on_purchase_item_change(sender, instance, **kwargs):
    recalculate_average_cost(instance.product)


@receiver(pre_delete, sender=Purchase)
def update_average_on_purchase_delete(sender, instance, **kwargs):
    products = {item.product for item in instance.items.all()}
    for p in products:
        recalculate_average_cost(p)


# =============================================================================
# Handle sale total recalculation (if needed)
# =============================================================================


@transaction.atomic
def recalculate_sale_total(sale):
    total = sale.items.aggregate(
        subtotal=Sum(
            ExpressionWrapper(
                F("quantity") * F("unit_selling_price"), output_field=DecimalField()
            )
        )
    )["subtotal"] or Decimal("0.00")
    total -= sale.discount or Decimal("0.00")
    if sale.total_amount != total:
        sale.total_amount = total
        sale.save(update_fields=["total_amount"])


# === Sale stock & total signals ===
@receiver(pre_save, sender=SaleItem)
def capture_old_quantity_sale(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = SaleItem.objects.only("quantity").get(pk=instance.pk)
            instance._old_quantity = old.quantity
        except SaleItem.DoesNotExist:
            instance._old_quantity = 0
    else:
        instance._old_quantity = 0


# =============================================================================
# Handle sale total recalculation and stock adjustments on SaleItem create/update/delete
# =============================================================================


@receiver(post_save, sender=SaleItem)
def handle_sale_item_change(sender, instance, created, **kwargs):
    old_qty = getattr(instance, "_old_quantity", 0)
    diff = instance.quantity - old_qty  # positive = returning to stock

    if diff != 0 or created:
        if created:
            change = -instance.quantity
            trans_type = "sale"
        else:
            change = diff * -1  # negative if sale increased
            trans_type = "sale" if change < 0 else "sale_reversal"

        update_stock(
            product=instance.product,
            quantity_change=change,
            transaction_type=trans_type,
            reason=f"Sale #{instance.sale.id} {'created' if created else 'updated'}",
            reference=str(instance.sale.id),
            user=instance.sale.sold_by,
        )

    recalculate_sale_total(instance.sale)
    if hasattr(instance, "_old_quantity"):
        del instance._old_quantity


@receiver(pre_delete, sender=Sale)
def handle_sale_delete(sender, instance, **kwargs):
    for item in instance.items.all():
        update_stock(
            product=item.product,
            quantity_change=item.quantity,  # return to stock
            transaction_type="sale_reversal",
            reason=f"Sale deleted (ID {instance.id})",
            reference=str(instance.id),
            user=None,
        )


@receiver(post_delete, sender=SaleItem)
def handle_sale_item_delete(sender, instance, **kwargs):
    if instance.sale_id and Sale.objects.filter(id=instance.sale_id).exists():
        recalculate_sale_total(instance.sale)


# Recalculate total if discount or other sale fields change
@receiver(post_save, sender=Sale)
def sale_post_save(sender, instance, **kwargs):
    recalculate_sale_total(instance)
