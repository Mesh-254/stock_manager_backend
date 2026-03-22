# shop_manager/views/report_views.py
from datetime import datetime, timedelta
from decimal import Decimal

from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DecimalField, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django_filters import FilterSet, DateFromToRangeFilter, ChoiceFilter, ModelChoiceFilter

from .models import Sale, SaleItem, Purchase, PurchaseItem, Expense, Stock, Returns, Category, Supplier
from accounts.models import User, UserRole


class BaseReportFilter(FilterSet):
    date_range = DateFromToRangeFilter(
        field_name='date',  # overridden per report
        label='Date Range',
        widget=forms.DateInput(attrs={
                'class': 'form-control datepicker',
                'placeholder': 'YYYY-MM-DD',
                'type': 'date',  # modern browsers show date picker
            }),
    )

    class Meta:
        fields = ['date_range']


class SalesReportFilter(BaseReportFilter):
    payment_status = ChoiceFilter(choices=Sale._meta.get_field('payment_status').choices)
    payment_method = ChoiceFilter(choices=Sale._meta.get_field('payment_method').choices if hasattr(Sale, 'payment_method') else [])
    sold_by = ModelChoiceFilter(queryset=User.objects.none())

    class Meta:
        model = Sale
        fields = ['payment_status', 'payment_method', 'sold_by']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = kwargs.get('request')
        if request:
            user = request.user
            if user.role == UserRole.SUPER_ADMIN:
                self.filters['sold_by'].queryset = User.objects.filter(role__in=[UserRole.SHOP_ADMIN, UserRole.CASHIER])
            else:
                self.filters['sold_by'].queryset = User.objects.filter(shop=user.shop)


@staff_member_required
def report_view(request, report_type):
    now = timezone.now()
    default_start = now - timedelta(days=30)
    default_end = now

    # Base context
    context = {
        'report_type': report_type,
        'title': '',
        'period': 'Custom Period',
        'metrics': {},
        'table_data': [],
        'extra_sections': {},
        'filters_form': None,
        'has_filters': bool(request.GET),
    }

    # Scoped queryset helper
    def scoped_qs(klass):
        qs = klass.objects.all()
        if request.user.role != UserRole.SUPER_ADMIN and request.user.shop:
            if hasattr(klass, 'shop'):
                qs = qs.filter(shop=request.user.shop)
            elif klass == SaleItem:
                qs = qs.filter(sale__shop=request.user.shop)
            elif klass == PurchaseItem:
                qs = qs.filter(purchase__shop=request.user.shop)
            elif klass == Stock:
                qs = qs.filter(product__shop=request.user.shop)
            elif klass == Returns:
                qs = qs.filter(sale_item__sale__shop=request.user.shop)
        return qs

    # ────────────────────────────────────────────────
    # SALES REPORT
    # ────────────────────────────────────────────────
    if report_type == 'sales':
        context['title'] = 'Sales Report'

        filterset = SalesReportFilter(
            request.GET or None,
            queryset=scoped_qs(Sale),
            request=request
        )

        # Default date range
        if not request.GET.get('date_range_after') and not request.GET.get('date_range_before'):
            filterset.form.initial['date_range'] = {
                'date_field__gte': default_start.date(),
                'date_field__lte': default_end.date()
            }

        sales_qs = filterset.qs

        # Aggregations
        agg = sales_qs.aggregate(
            total_revenue=Sum('total_amount', default=Decimal('0.00')),
            total_profit=Sum(
                ExpressionWrapper(
                    (F('items__unit_selling_price') - F('items__unit_cost_price')) * F('items__quantity'),
                    output_field=DecimalField(max_digits=15, decimal_places=2)
                ),
                default=Decimal('0.00')
            ),
            order_count=Count('id'),
            avg_order=Avg('total_amount', default=Decimal('0.00')),
        )

        top_products = SaleItem.objects.filter(sale__in=sales_qs).values(
            'product__name', 'product__category__name'
        ).annotate(
            qty_sold=Sum('quantity'),
            revenue=Sum(F('quantity') * F('unit_selling_price')),
            profit=Sum((F('unit_selling_price') - F('unit_cost_price')) * F('quantity'))
        ).order_by('-revenue')[:10]

        context.update({
            'metrics': {
                'Total Revenue': f"KES {agg['total_revenue']:,.2f}",
                'Gross Profit': f"KES {agg['total_profit']:,.2f}",
                'Orders': agg['order_count'],
                'Avg Order Value': f"KES {agg['avg_order']:,.2f}",
            },
            'top_products': top_products,
            'recent_sales': sales_qs.order_by('-sale_date')[:20].select_related('sold_by'),
            'filters_form': filterset.form,
        })

    # ────────────────────────────────────────────────
    # PURCHASE REPORT
    # ────────────────────────────────────────────────
    elif report_type == 'purchases':
        context['title'] = 'Purchase Report'

        purchases_qs = scoped_qs(Purchase)

        agg = purchases_qs.aggregate(
            total_cost=Sum('total_amount', default=Decimal('0.00')),
            purchase_count=Count('id'),
        )

        top_suppliers = Purchase.objects.filter(id__in=purchases_qs).values(
            'supplier__name'
        ).annotate(
            total_spent=Sum('total_amount'),
            purchase_count=Count('id')
        ).order_by('-total_spent')[:8]

        context.update({
            'metrics': {
                'Total Purchases': f"KES {agg['total_cost']:,.2f}",
                'Purchase Transactions': agg['purchase_count'],
            },
            'top_suppliers': top_suppliers,
            'recent_purchases': purchases_qs.order_by('-purchase_date')[:20],
        })

    # ────────────────────────────────────────────────
    # EXPENSE REPORT
    # ────────────────────────────────────────────────
    elif report_type == 'expenses':
        context['title'] = 'Expense Report'

        expenses_qs = scoped_qs(Expense)

        agg = expenses_qs.aggregate(
            total_expense=Sum('amount', default=Decimal('0.00')),
            count=Count('id'),
        )

        by_type = expenses_qs.values('expense_type').annotate(
            total=Sum('amount')
        ).order_by('-total')

        context.update({
            'metrics': {
                'Total Expenses': f"KES {agg['total_expense']:,.2f}",
                'Expense Entries': agg['count'],
            },
            'expenses_by_type': by_type,
            'recent_expenses': expenses_qs.order_by('-date')[:20],
        })

    # ────────────────────────────────────────────────
    # STOCK REPORT
    # ────────────────────────────────────────────────
    elif report_type == 'stock':
        context['title'] = 'Stock Overview & Alerts'

        stock_qs = scoped_qs(Stock)

        low_stock = stock_qs.filter(quantity__lte=F('product__reorder_level'), quantity__gt=0)
        zero_stock = stock_qs.filter(quantity=0)

        total_value_selling = stock_qs.aggregate(
            value=Sum(F('quantity') * F('product__selling_price'), default=Decimal('0.00'))
        )['value']

        total_value_cost = stock_qs.aggregate(
            value=Sum(F('quantity') * F('product__cost_price'), default=Decimal('0.00'))
        )['value']

        context.update({
            'metrics': {
                'Current Stock Value (selling)': f"KES {total_value_selling:,.2f}",
                'Current Stock Value (cost)': f"KES {total_value_cost:,.2f}",
                'Low Stock Items': low_stock.count(),
                'Out of Stock Items': zero_stock.count(),
            },
            'low_stock_items': low_stock.select_related('product')[:15],
            'zero_stock_items': zero_stock.select_related('product')[:15],
        })

    # ────────────────────────────────────────────────
    # RETURNS REPORT
    # ────────────────────────────────────────────────
    elif report_type == 'returns':
        context['title'] = 'Returns & Refunds Report'

        returns_qs = scoped_qs(Returns)

        agg = returns_qs.aggregate(
            total_returns=Count('id'),
            total_refunded=Sum('refund_amount', default=Decimal('0.00')),
        )

        top_returned = returns_qs.values(
            'sale_item__product__name', 'sale_item__product__category__name'
        ).annotate(
            count=Count('id'),
            total_refund=Sum('refund_amount')
        ).order_by('-count')[:10]

        context.update({
            'metrics': {
                'Total Returns': agg['total_returns'],
                'Total Refunded': f"KES {agg['total_refunded']:,.2f}",
            },
            'top_returned_products': top_returned,
            'recent_returns': returns_qs.order_by('-return_date')[:20].select_related('sale_item__product'),
        })

    else:
        return HttpResponse("Invalid report type", status=400)

    # PDF Export
    if request.GET.get('export') == 'pdf':
        from weasyprint import HTML
        html_content = render(request, f'reports/{report_type}_print.html', context).content.decode('utf-8')
        pdf = HTML(string=html_content).write_pdf()
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{report_type}_report_{now.strftime("%Y-%m-%d")}.pdf"'
        response.write(pdf)
        return response

    return render(request, 'reports/base_report.html', context)