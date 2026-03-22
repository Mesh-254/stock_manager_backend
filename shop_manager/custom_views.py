from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
from shop_manager.permissions import IsCashierOrHigher
from shop_manager.signals import recalculate_sale_total
from .models import Sale, SaleItem, Supplier, Product, Brand
from accounts.models import User, UserRole
from .models import Supplier, Product, Brand, Purchase
from django.forms import inlineformset_factory, ModelForm
from django import forms
from .models import Purchase, PurchaseItem
from django.db import transaction
from django.db.models import F
import json
from decimal import Decimal


@staff_member_required
@permission_classes(
    [IsAuthenticated, IsCashierOrHigher]
)  # Adjust if cashiers can purchase
def add_purchase_view(request):
    if request.method == "GET":
        suppliers = Supplier.objects.values("id", "name").order_by("name")
        products = Product.objects.values("id", "name").order_by(
            "name"
        )  # Faster than all()
        brands = Brand.objects.values("id", "name").order_by("name")

        context = {
            "api_url": "/api/shopmanager/purchases/",
            "suppliers": list(suppliers),
            "products": list(products),
            "brands": list(brands),
        }
        return render(request, "shop_manager/add_purchase.html", context)

    return redirect("admin:shop_manager_purchase_changelist")


class PurchaseForm(ModelForm):
    class Meta:
        model = Purchase
        fields = ['supplier', 'purchase_date', 'payment_status', 'payment_method']
        widgets = {
            'purchase_date': forms.DateInput(attrs={'type': 'date'}),
        }

class PurchaseItemForm(ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ['product', 'brand', 'quantity', 'unit_cost_price']

@staff_member_required
# If you need DRF permissions in function view, you can manually check
def edit_purchase_view(request, purchase_id):
    purchase = get_object_or_404(Purchase, id=purchase_id)

    # Your existing permission check
    if request.user.role == UserRole.SHOP_ADMIN and purchase.shop != request.user.shop:
        return redirect("admin:shop_manager_purchase_changelist")

    PurchaseItemFormSet = inlineformset_factory(
        Purchase, PurchaseItem,
        form=PurchaseItemForm,
        fields=('product', 'brand', 'quantity', 'unit_cost_price'),
        can_delete=True,
        extra=0
    )

    if request.method == 'POST':
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=purchase)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                # Recalculate total_amount accurately on server
                purchase.total_amount = sum(
                    item.quantity * item.unit_cost_price
                    for item in purchase.items.all()
                )
                purchase.save()
            return redirect('admin:shop_manager_purchase_changelist')
    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseItemFormSet(instance=purchase)

    return render(request, 'shop_manager/edit_purchase.html', {
        'form': form,
        'formset': formset,
        'purchase': purchase,
    })


@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def detail_purchase_view(request, purchase_id):
    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier', 'shop', 'created_by')
        .prefetch_related('items__product', 'items__brand'),
        id=purchase_id
    )

    # Permission check
    if request.user.role == UserRole.SHOP_ADMIN and purchase.shop != request.user.shop:
        return redirect("admin:shop_manager_purchase_changelist")

    context = {
        "purchase": purchase,
    }
    return render(request, "shop_manager/detail_purchase.html", context)



# =============================================================================
# Sale Views (Add/Edit/Detail)
# =============================================================================

class SaleForm(ModelForm):
    class Meta:
        model = Sale
        fields = ['sale_date', 'payment_status', 'payment_method', 'discount']
        widgets = {'sale_date': forms.DateInput(attrs={'type': 'date'})}

class SaleItemForm(ModelForm):
    class Meta:
        model = SaleItem
        fields = ['product', 'quantity', 'unit_selling_price']

@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def add_sale_view(request):
    if request.method == "GET":
        products_qs = Product.objects.select_related('stock').annotate(
            stock_qty=F('stock__quantity')
        ).values(
            'id', 'name', 'selling_price', 'stock_qty'
        ).order_by('name')

        products_list = list(products_qs)

        context = {
            "api_url": "/api/shopmanager/sales/",
            "products_json": json.dumps(products_list, default=str),  # Safe JSON string
        }
        return render(request, "shop_manager/add_sale.html", context)
    return redirect("admin:shop_manager_sale_changelist")

@staff_member_required
@permission_classes([IsAuthenticated, IsCashierOrHigher])
def edit_sale_view(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    if request.user.role == UserRole.SHOP_ADMIN and sale.shop != request.user.shop:
        return redirect("admin:shop_manager_sale_changelist")

    SaleItemFormSet = inlineformset_factory(
        Sale, SaleItem, form=SaleItemForm,
        fields=('product', 'quantity', 'unit_selling_price'),
        extra=0, can_delete=True
    )

    if request.method == 'POST':
        form = SaleForm(request.POST, instance=sale)
        formset = SaleItemFormSet(request.POST, instance=sale)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
                recalculate_sale_total(sale)
            return redirect('admin:shop_manager_sale_changelist')
    else:
        form = SaleForm(instance=sale)
        formset = SaleItemFormSet(instance=sale)

    return render(request, 'shop_manager/edit_sale.html', {
        'form': form, 'formset': formset, 'sale': sale,
    })


@staff_member_required
def detail_sale_view(request, sale_id):
    sale = get_object_or_404(
        Sale.objects.select_related('shop', 'sold_by')
        .prefetch_related('items__product'), id=sale_id
    )
    if request.user.role == UserRole.SHOP_ADMIN and sale.shop != request.user.shop:
        return redirect("admin:shop_manager_sale_changelist")

    # Pre-compute subtotal and current unit cost for each item
    enriched_items = []
    for item in sale.items.all():
        current_cost = item.product.average_cost_price or Decimal('0.00')
        subtotal = item.unit_selling_price * Decimal(item.quantity)

        enriched_items.append({
            'product_name': item.product.name,
            'quantity': item.quantity,
            'current_unit_cost': current_cost,
            'unit_selling_price': item.unit_selling_price,
            'subtotal': subtotal,
        })

    context = {
        'sale': sale,
        'enriched_items': enriched_items,
    }
    return render(request, "shop_manager/detail_sale.html", context)