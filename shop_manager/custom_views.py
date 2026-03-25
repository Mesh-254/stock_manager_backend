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


from .models import Purchase, PurchaseItem, Usage, UsageItem, Supplier, Product
from .permissions import IsCashierOrHigher
from accounts.models import UserRole


# =============================================================================
# PURCHASE VIEWS
# =============================================================================


class PurchaseForm(ModelForm):
    class Meta:
        model = Purchase
        fields = ["supplier", "purchase_date", "payment_status", "payment_method"]
        widgets = {"purchase_date": forms.DateInput(attrs={"type": "date"})}


class PurchaseItemForm(ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ["product", "quantity", "unit_cost_price"]


@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def add_purchase_view(request):
    """Template form to create a new Purchase + items."""
    if request.method == "GET":
        suppliers = Supplier.objects.values("id", "name").order_by("name")
        products = Product.objects.values("id", "name").order_by("name")

        context = {
            "suppliers": list(suppliers),
            "products": list(products),
            "api_url": "/api/purchases/",  # for any JS that needs it
        }
        return render(request, "shop_manager/add_purchase.html", context)

    return redirect("admin:shop_manager_purchase_changelist")


@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def edit_purchase_view(request, purchase_id):
    """Edit existing Purchase and its items using formsets."""
    purchase = get_object_or_404(Purchase, id=purchase_id)

    # Shop-scoped permission
    if request.user.role == UserRole.SHOP_ADMIN and purchase.shop != request.user.shop:
        return redirect("admin:shop_manager_purchase_changelist")

    PurchaseItemFormSet = inlineformset_factory(
        Purchase,
        PurchaseItem,
        form=PurchaseItemForm,
        fields=("product", "quantity", "unit_cost_price"),
        can_delete=True,
        extra=0,
    )

    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=purchase)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                purchase.update_total()  # model method
                purchase.update_stock(
                    user=request.user
                )  # triggers weighted average + stock
            return redirect("admin:shop_manager_purchase_changelist")
    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseItemFormSet(instance=purchase)

    return render(
        request,
        "shop_manager/edit_purchase.html",
        {
            "form": form,
            "formset": formset,
            "purchase": purchase,
        },
    )


@staff_member_required
def detail_purchase_view(request, purchase_id):
    """Read-only detail view for a Purchase."""
    purchase = get_object_or_404(
        Purchase.objects.select_related(
            "supplier", "shop", "created_by"
        ).prefetch_related("items__product"),
        id=purchase_id,
    )

    if request.user.role == UserRole.SHOP_ADMIN and purchase.shop != request.user.shop:
        return redirect("admin:shop_manager_purchase_changelist")

    context = {"purchase": purchase}
    return render(request, "shop_manager/detail_purchase.html", context)


# =============================================================================
# USAGE VIEWS (formerly Sale)
# =============================================================================


class UsageForm(ModelForm):
    class Meta:
        model = Usage
        fields = ["usage_date", "note"]
        widgets = {"usage_date": forms.DateInput(attrs={"type": "date"})}


class UsageItemForm(ModelForm):
    class Meta:
        model = UsageItem
        fields = ["product", "quantity"]


@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def add_usage_view(request):  # renamed from add_sale_view
    """Template form to record daily usage/consumption."""
    if request.method == "GET":
        products_qs = (
            Product.objects.select_related("stock")
            .annotate(stock_qty=F("stock__quantity"))
            .values("id", "name", "stock_qty", "unit")
            .order_by("name")
        )

        context = {
            "products_json": json.dumps(list(products_qs), default=str),
            "api_url": "/api/sales/",  # legacy name kept for frontend JS
        }
        return render(
            request, "shop_manager/add_sale.html", context
        )  # keep template name if you want

    return redirect(
        "admin:shop_manager_usage_changelist"
    )  # adjust admin changelist if needed


@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def edit_usage_view(request, usage_id):
    """Edit existing Usage and its items."""
    usage = get_object_or_404(Usage, id=usage_id)

    if request.user.role == UserRole.SHOP_ADMIN and usage.shop != request.user.shop:
        return redirect("admin:shop_manager_usage_changelist")

    UsageItemFormSet = inlineformset_factory(
        Usage,
        UsageItem,
        form=UsageItemForm,
        fields=("product", "quantity"),
        can_delete=True,
        extra=0,
    )

    if request.method == "POST":
        form = UsageForm(request.POST, instance=usage)
        formset = UsageItemFormSet(request.POST, instance=usage)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                usage.update_total()
                usage.deduct_stock(user=request.user)
            return redirect("admin:shop_manager_usage_changelist")
    else:
        form = UsageForm(instance=usage)
        formset = UsageItemFormSet(instance=usage)

    return render(
        request,
        "shop_manager/edit_sale.html",
        {  # keep template name if needed
            "form": form,
            "formset": formset,
            "usage": usage,  # renamed variable
        },
    )


@staff_member_required
def detail_usage_view(request, usage_id):
    """Read-only detail view for Usage."""
    usage = get_object_or_404(
        Usage.objects.select_related("shop", "recorded_by").prefetch_related(
            "items__product"
        ),
        id=usage_id,
    )

    if request.user.role == UserRole.SHOP_ADMIN and usage.shop != request.user.shop:
        return redirect("admin:shop_manager_usage_changelist")

    context = {"usage": usage}
    return render(request, "shop_manager/detail_sale.html", context)
