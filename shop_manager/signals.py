"""
Signals for Shop Manager

Minimal set of signals that complement (but do not duplicate) model methods and serializers.
Only essential hooks are kept:
- Auto-create Stock record on Product creation.
- Safety-net total recalculation for Purchase/Usage (in case items are edited outside serializers).

All heavy lifting (stock movement, weighted average cost) is handled in models/serializers/custom_views.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal

from .models import Product, Stock, Purchase, Usage


# =============================================================================
# PRODUCT → STOCK
# =============================================================================
@receiver(post_save, sender=Product)
def create_initial_stock(sender, instance, created, **kwargs):
    """
    Ensure every new Product has a corresponding Stock record.
    """
    if created:
        Stock.objects.get_or_create(product=instance, defaults={"quantity": Decimal("0.00")})


# =============================================================================
# PURCHASE TOTAL SAFETY NET
# =============================================================================
@receiver(post_save, sender=Purchase)
def purchase_post_save(sender, instance, **kwargs):
    """Ensure total_amount is always correct after any save."""
    if instance.items.exists():
        instance.update_total()


# =============================================================================
# USAGE TOTAL SAFETY NET
# =============================================================================
@receiver(post_save, sender=Usage)
def usage_post_save(sender, instance, **kwargs):
    """Ensure total_cost is always correct after any save."""
    if instance.items.exists():
        instance.update_total()


# =============================================================================
# (Optional) Average cost recalculation can be triggered here if needed,
# but it is already handled inside Purchase.update_stock() for normal flows.
# =============================================================================