"""
Custom Template-Based Views for Purchase & Usage Management

These function-based views provide HTML forms for the Django admin / staff interface.
They are kept for backward compatibility with your existing templates (add_*.html, edit_*.html, etc.).

Design decisions:
- All business logic (stock updates, average cost recalculation, total_cost) is delegated to the models/serializers.
- Forms are simple inline formsets.
- Permission checks reuse the same classes as the ViewSets.
- Renamed "sale" → "usage" everywhere to match current models.
- Removed non-existent fields (discount, selling_price, payment_method on Usage).
- Context now includes products and suppliers for dropdowns in templates.
"""

from decimal import Decimal
import json
from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.forms import inlineformset_factory, ModelForm
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
#  import DjangoValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Purchase, PurchaseItem, Usage, UsageItem, Supplier, Product
from .permissions import IsCashierOrHigher
from accounts.models import UserRole


# =============================================================================
# PURCHASE VIEWS
# =============================================================================


class PurchaseForm(ModelForm):
    """Form for creating and editing Purchase records."""
    class Meta:
        model = Purchase
        fields = ["supplier", "purchase_date", "payment_status", "payment_method"]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
        }


PurchaseItemFormSet = inlineformset_factory(
    Purchase,
    PurchaseItem,
    fields=("product", "quantity", "unit_cost_price"),
    extra=1,
    can_delete=True,
)


@staff_member_required
def add_purchase_view(request):
    """
    Add new Purchase using template form.
    
    Context:
    - form: PurchaseForm instance
    - formset: PurchaseItemFormSet instance
    - suppliers: Available suppliers for current shop (for template reference)
    - products: Available products for current shop (for template dropdowns)
    """
    if request.method == "POST":
        form = PurchaseForm(request.POST)
        formset = PurchaseItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                purchase = form.save(commit=False)
                purchase.created_by = request.user
                # Assign shop from user if available
                if hasattr(request.user, 'shop') and request.user.shop:
                    purchase.shop = request.user.shop
                purchase.save()

                # Save formset items
                formset.instance = purchase
                formset.save()

                # Recalculate totals and update stock
                purchase.update_total()
                purchase.update_stock(user=request.user)

            return redirect('admin:shop_manager_purchase_changelist')

    else:
        form = PurchaseForm()
        formset = PurchaseItemFormSet()

    # Get shop from user
    shop = getattr(request.user, 'shop', None)
    
    # Context with products and suppliers for dropdowns
    context = {
        'form': form,
        'formset': formset,
        'suppliers': Supplier.objects.filter(shop=shop) if shop else Supplier.objects.none(),
        'products': Product.objects.filter(shop=shop, is_active=True) if shop else Product.objects.none(),
    }

    return render(request, 'shop_manager/add_purchase.html', context)


@staff_member_required
def edit_purchase_view(request, purchase_id):
    """
    Edit existing Purchase.
    
    Filters by shop if user is ShopAdmin to ensure data isolation.
    
    Context:
    - form: PurchaseForm instance with existing data
    - formset: PurchaseItemFormSet with existing items
    - purchase: The Purchase object being edited
    - suppliers: Available suppliers for current shop
    - products: Available products for current shop
    """
    purchase = get_object_or_404(Purchase, id=purchase_id)

    # Permission check: ShopAdmin can only edit their own shop's purchases
    if request.user.role == "ShopAdmin" and purchase.shop != request.user.shop:
        return redirect('admin:shop_manager_purchase_changelist')

    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=purchase)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                purchase.update_total()
                purchase.update_stock(user=request.user)
            return redirect('admin:shop_manager_purchase_changelist')
    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseItemFormSet(instance=purchase)

    # Get shop from purchase object
    shop = purchase.shop
    
    context = {
        'form': form,
        'formset': formset,
        'purchase': purchase,
        'suppliers': Supplier.objects.filter(shop=shop) if shop else Supplier.objects.none(),
        'products': Product.objects.filter(shop=shop, is_active=True) if shop else Product.objects.none(),
    }

    return render(request, 'shop_manager/edit_purchase.html', context)


@staff_member_required
def detail_purchase_view(request, purchase_id):
    """
    View Purchase details (read-only).
    
    Includes all related data: supplier, items with product details, and payment info.
    
    Context:
    - purchase: The Purchase object with related data preloaded
    """
    purchase = get_object_or_404(
        Purchase.objects.select_related('shop', 'supplier', 'created_by')
                       .prefetch_related('items__product'), 
        id=purchase_id
    )

    # Permission check: ShopAdmin can only view their own shop's purchases
    if request.user.role == "ShopAdmin" and purchase.shop != request.user.shop:
        return redirect('admin:shop_manager_purchase_changelist')

    context = {'purchase': purchase}
    return render(request, 'shop_manager/detail_purchase.html', context)


# =============================================================================
# USAGE VIEWS (formerly Sale)
# =============================================================================

class UsageForm(ModelForm):
    """Form for creating and editing Usage records."""
    class Meta:
        model = Usage
        fields = ["usage_date", "note"]
        widgets = {
            "usage_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }


UsageItemFormSet = inlineformset_factory(
    Usage,
    UsageItem,
    fields=("product", "quantity"),
    extra=1,
    can_delete=True,
)

@staff_member_required
def add_usage_view(request):
    """
    Record new Usage with proper stock validation and user-friendly error messages.
    """
    if request.method == "POST":
        form = UsageForm(request.POST)
        formset = UsageItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    usage = form.save(commit=False)
                    usage.recorded_by = request.user
                    if hasattr(request.user, 'shop') and request.user.shop:
                        usage.shop = request.user.shop
                    usage.save()

                    formset.instance = usage
                    formset.save()

                    usage.update_total()
                    usage.deduct_stock(user=request.user)

                return redirect('admin:shop_manager_usage_changelist')

            except DjangoValidationError as e:
                # Handle stock validation error gracefully
                error_msg = str(e)
                if isinstance(e, list):
                    error_msg = e[0] if e else "Stock error occurred"
                form.add_error(None, error_msg)

            except Exception as e:
                form.add_error(None, f"An unexpected error occurred: {str(e)}")

    else:
        form = UsageForm()
        formset = UsageItemFormSet()

    shop = getattr(request.user, 'shop', None)
    
    context = {
        'form': form,
        'formset': formset,
        'products': Product.objects.filter(shop=shop, is_active=True) if shop else Product.objects.none(),
    }

    return render(request, 'shop_manager/add_usage.html', context)


@staff_member_required
def edit_usage_view(request, usage_id):
    """
    Edit existing Usage record.
    
    Filters by shop if user is ShopAdmin to ensure data isolation.
    
    Context:
    - form: UsageForm instance with existing data
    - formset: UsageItemFormSet with existing items
    - usage: The Usage object being edited
    - products: Available products for current shop (with average_cost_price)
    """
    usage = get_object_or_404(Usage, id=usage_id)

    # Permission check: ShopAdmin can only edit their own shop's usage records
    if request.user.role == "ShopAdmin" and usage.shop != request.user.shop:
        return redirect('admin:shop_manager_usage_changelist')

    if request.method == "POST":
        form = UsageForm(request.POST, instance=usage)
        formset = UsageItemFormSet(request.POST, instance=usage)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                usage.update_total()
                usage.deduct_stock(user=request.user)
            return redirect('admin:shop_manager_usage_changelist')
    else:
        form = UsageForm(instance=usage)
        formset = UsageItemFormSet(instance=usage)

    # Get shop from usage object
    shop = usage.shop
    
    context = {
        'form': form,
        'formset': formset,
        'usage': usage,
        'products': Product.objects.filter(shop=shop, is_active=True) if shop else Product.objects.none(),
    }

    return render(request, 'shop_manager/edit_usage.html', context)


@staff_member_required
def detail_usage_view(request, usage_id):
    """
    View Usage details (read-only).
    
    Includes all related data: items with product details, costs, and notes.
    
    Context:
    - usage: The Usage object with related data preloaded
    """
    usage = get_object_or_404(
        Usage.objects.select_related('shop', 'recorded_by')
                    .prefetch_related('items__product'),
        id=usage_id
    )

    # Permission check: ShopAdmin can only view their own shop's usage records
    if request.user.role == "ShopAdmin" and usage.shop != request.user.shop:
        return redirect('admin:shop_manager_usage_changelist')

    context = {'usage': usage}
    return render(request, 'shop_manager/detail_usage.html', context)
