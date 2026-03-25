"""
Report Views for School Shop Inventory System

This module provides server-rendered HTML reports for the Django admin / staff interface.
It is used for quick managerial overviews (monthly usage cost, purchases, stock alerts, expenses).

Design decisions:
- All reports are shop-scoped for multi-tenancy security.
- Uses Django-Filter for date ranges and simple filters.
- Focuses on COST (not profit) because this is a school consumption system.
- Heavy use of select_related/prefetch_related + annotations for performance.
- PDF export via WeasyPrint (optional).
- Compatible with the current Usage/Purchase/Stock models (no legacy Sale fields).
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, F, Avg  # ← Fixed: added Avg
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django_filters import FilterSet, DateFromToRangeFilter, ModelChoiceFilter

from .models import Usage, UsageItem, Purchase, PurchaseItem, Expense, Stock
from accounts.models import User


class BaseReportFilter(FilterSet):
    """Common date-range filter used by all reports."""

    date_range = DateFromToRangeFilter(
        field_name="date",  # overridden per report
        label="Date Range",
    )

    class Meta:
        fields = ["date_range"]


class UsageReportFilter(BaseReportFilter):
    """Filter for daily usage/consumption reports."""

    recorded_by = ModelChoiceFilter(queryset=User.objects.none())

    class Meta:
        model = Usage
        fields = ["recorded_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = kwargs.get("request")
        if request and hasattr(request.user, "shop") and request.user.shop:
            self.filters["recorded_by"].queryset = User.objects.filter(
                shop=request.user.shop
            )


@staff_member_required
def report_view(request, report_type):
    """
    Main report dispatcher.
    Renders HTML reports for staff users.
    Supports PDF export via ?export=pdf.
    """
    now = timezone.now()
    default_start = now - timedelta(days=30)
    default_end = now

    context = {
        "report_type": report_type,
        "title": "",
        "period": "Last 30 days (default)",
        "metrics": {},
        "table_data": [],
        "filters_form": None,
        "has_filters": bool(request.GET),
    }

    # Helper to scope querysets by current user's shop
    def scoped_qs(klass):
        qs = klass.objects.all()
        if (
            request.user.role != "SuperAdmin"
            and hasattr(request.user, "shop")
            and request.user.shop
        ):
            if hasattr(klass, "shop"):
                qs = qs.filter(shop=request.user.shop)
            elif klass == UsageItem:
                qs = qs.filter(usage__shop=request.user.shop)
            elif klass == PurchaseItem:
                qs = qs.filter(purchase__shop=request.user.shop)
            elif klass == Stock:
                qs = qs.filter(product__shop=request.user.shop)
        return qs

    # ========================= USAGE REPORT =========================
    if report_type == "usage":
        context["title"] = "Usage / Consumption Report"

        filterset = UsageReportFilter(
            request.GET or None, queryset=scoped_qs(Usage), request=request
        )
        if not request.GET.get("date_range_after") and not request.GET.get(
            "date_range_before"
        ):
            filterset.form.initial["date_range"] = {
                "gte": default_start.date(),
                "lte": default_end.date(),
            }

        usage_qs = filterset.qs

        # Aggregations
        agg = usage_qs.aggregate(
            total_cost=Sum("total_cost", default=Decimal("0.00")),
            usage_count=Count("id"),
            avg_daily=Avg("total_cost", default=Decimal("0.00")),
        )

        top_items = (
            UsageItem.objects.filter(usage__in=usage_qs)
            .values("product__name", "product__category__name", "product__unit")
            .annotate(
                total_quantity=Sum("quantity"),
                total_cost=Sum("cost"),
            )
            .order_by("-total_cost")[:10]
        )

        context.update(
            {
                "metrics": {
                    "Total Cost Used": f"KES {agg['total_cost']:,.2f}",
                    "Usage Entries": agg["usage_count"],
                    "Avg Daily Cost": f"KES {agg['avg_daily']:,.2f}",
                },
                "top_items": top_items,
                "recent_usages": usage_qs.order_by("-usage_date")[:20].select_related(
                    "recorded_by"
                ),
                "filters_form": filterset.form,
            }
        )

    # ========================= PURCHASE REPORT =========================
    elif report_type == "purchases":
        context["title"] = "Purchase Report"

        purchases_qs = scoped_qs(Purchase)

        agg = purchases_qs.aggregate(
            total_cost=Sum("total_amount", default=Decimal("0.00")),
            purchase_count=Count("id"),
        )

        top_suppliers = (
            purchases_qs.values("supplier__name")
            .annotate(total_spent=Sum("total_amount"), count=Count("id"))
            .order_by("-total_spent")[:8]
        )

        context.update(
            {
                "metrics": {
                    "Total Purchase Cost": f"KES {agg['total_cost']:,.2f}",
                    "Purchase Transactions": agg["purchase_count"],
                },
                "top_suppliers": top_suppliers,
                "recent_purchases": purchases_qs.order_by("-purchase_date")[:20],
            }
        )

    # ========================= EXPENSE REPORT =========================
    elif report_type == "expenses":
        context["title"] = "Expense Report"

        expenses_qs = scoped_qs(Expense)

        agg = expenses_qs.aggregate(
            total_expense=Sum("amount", default=Decimal("0.00")),
            count=Count("id"),
        )

        by_type = (
            expenses_qs.values("expense_type")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )

        context.update(
            {
                "metrics": {
                    "Total Expenses": f"KES {agg['total_expense']:,.2f}",
                    "Expense Entries": agg["count"],
                },
                "expenses_by_type": by_type,
                "recent_expenses": expenses_qs.order_by("-date")[:20],
            }
        )

    # ========================= STOCK REPORT =========================
    elif report_type == "stock":
        context["title"] = "Stock Overview & Alerts"

        stock_qs = scoped_qs(Stock)

        low_stock = stock_qs.filter(
            quantity__lte=F("product__reorder_level"), quantity__gt=0
        )
        zero_stock = stock_qs.filter(quantity=0)

        total_cost_value = stock_qs.aggregate(
            value=Sum(
                F("quantity") * F("product__average_cost_price"),
                default=Decimal("0.00"),
            )
        )["value"]

        context.update(
            {
                "metrics": {
                    "Current Stock Value (at avg cost)": f"KES {total_cost_value:,.2f}",
                    "Low Stock Items": low_stock.count(),
                    "Out of Stock Items": zero_stock.count(),
                },
                "low_stock_items": low_stock.select_related("product")[:15],
                "zero_stock_items": zero_stock.select_related("product")[:15],
            }
        )

    else:
        return HttpResponse("Invalid report type", status=400)

    # Optional PDF export
    if request.GET.get("export") == "pdf":
        from weasyprint import HTML

        html_content = render(
            request, f"reports/{report_type}_print.html", context
        ).content.decode("utf-8")
        pdf = HTML(string=html_content).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{report_type}_report_{now.strftime("%Y-%m-%d")}.pdf"'
        )
        return response

    return render(request, "reports/base_report.html", context)
