"""
Report Views for School Shop Inventory System
Fully aligned with current models + date-range support.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, F, Avg
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django_filters import FilterSet, DateFromToRangeFilter, ModelChoiceFilter

from .models import Usage, UsageItem, Purchase, PurchaseItem, Expense, Stock
from accounts.models import User


# =============================================================================
# FILTERSETS (fixed field names + shop scoping)
# =============================================================================
class BaseReportFilter(FilterSet):
    date_range = DateFromToRangeFilter(field_name="date")  # overridden per subclass

    class Meta:
        fields = ["date_range"]


class SalesReportFilter(BaseReportFilter):  # renamed from UsageReportFilter
    date_range = DateFromToRangeFilter(field_name="usage_date")
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


class PurchaseReportFilter(BaseReportFilter):
    date_range = DateFromToRangeFilter(field_name="purchase_date")

    class Meta:
        model = Purchase
        fields = []


class ExpenseReportFilter(BaseReportFilter):
    date_range = DateFromToRangeFilter(field_name="date")

    class Meta:
        model = Expense
        fields = []


@staff_member_required
def report_view(request, report_type):
    now = timezone.now()
    default_start = now - timedelta(days=30)
    default_end = now

    context = {
        "report_type": report_type,
        "title": "",
        "now": now,                    # ← required by all print templates
        "metrics": {},
        "metrics_items": [],
        "filters_form": None,
        "has_filters": bool(request.GET),
    }

    def scoped_qs(klass):
        qs = klass.objects.all()
        if request.user.role != "SuperAdmin" and hasattr(request.user, "shop") and request.user.shop:
            if hasattr(klass, "shop"):
                qs = qs.filter(shop=request.user.shop)
            elif klass == UsageItem:
                qs = qs.filter(usage__shop=request.user.shop)
            elif klass == PurchaseItem:
                qs = qs.filter(purchase__shop=request.user.shop)
            elif klass == Stock:
                qs = qs.filter(product__shop=request.user.shop)
        return qs

    # ========================= SALES / USAGE REPORT =========================
    if report_type == "sales":          # ← use "sales" to match your templates
        context["title"] = "Sales / Usage Report"

        filterset = SalesReportFilter(
            request.GET or None, queryset=scoped_qs(Usage), request=request
        )
        if not request.GET.get("date_range_after") and not request.GET.get("date_range_before"):
            filterset.form.initial["date_range"] = {
                "gte": default_start.date(),
                "lte": default_end.date(),
            }

        usage_qs = filterset.qs

        agg = usage_qs.aggregate(
            total_cost=Sum("total_cost", default=Decimal("0.00")),
            usage_count=Count("id"),
            avg_daily=Avg("total_cost", default=Decimal("0.00")),
        )

        top_items_qs = (
            UsageItem.objects.filter(usage__in=usage_qs)
            .values("product__name", "product__category__name")
            .annotate(
                total_quantity=Sum("quantity"),
                total_cost=Sum("cost"),
            )
            .order_by("-total_cost")[:10]
        )

        # Enrich for your existing print/web templates
        top_products = [
            {
                "name": item["product__name"],
                "category": {"name": item.get("product__category__name") or "—"},
                "qty_sold": item["total_quantity"],
                "revenue": item["total_cost"],      # using cost as "revenue" (consumption system)
                "profit": Decimal("0.00"),          # legacy field – kept for template compatibility
            }
            for item in top_items_qs
        ]

        recent_usages = usage_qs.order_by("-usage_date")[:20].select_related("recorded_by")

        recent_sales = [  # dummy mapping so sales_print.html works unchanged
            {
                "id": u.id,
                "sale_date": u.usage_date,           # template expects sale_date
                "sold_by": u.recorded_by,            # has .full_name
                "total_amount": u.total_cost,
                "payment_status": "PAID",            # legacy field
            }
            for u in recent_usages
        ]

        context.update({
            "metrics": {
                "Total Cost Used": f"KES {agg['total_cost']:,.2f}",
                "Usage Entries": agg["usage_count"],
                "Avg Daily Cost": f"KES {agg['avg_daily']:,.2f}",
            },
            "metrics_items": [
                ["Total Cost Used", f"KES {agg['total_cost']:,.2f}"],
                ["Usage Entries", agg["usage_count"]],
                ["Avg Daily Cost", f"KES {agg['avg_daily']:,.2f}"],
            ],
            "top_products": top_products,
            "recent_sales": recent_sales,
            "filters_form": filterset.form,
        })

    # ========================= PURCHASES REPORT =========================
    elif report_type == "purchases":
        context["title"] = "Purchases Report"

        filterset = PurchaseReportFilter(
            request.GET or None, queryset=scoped_qs(Purchase)
        )
        if not request.GET.get("date_range_after") and not request.GET.get("date_range_before"):
            filterset.form.initial["date_range"] = {
                "gte": default_start.date(),
                "lte": default_end.date(),
            }

        purchases_qs = filterset.qs

        agg = purchases_qs.aggregate(
            total_cost=Sum("total_amount", default=Decimal("0.00")),
            purchase_count=Count("id"),
        )

        # Top purchased products (matches purchase_print.html)
        top_purchases_qs = (
            PurchaseItem.objects.filter(purchase__in=purchases_qs)
            .select_related("product", "purchase__supplier")
            .values("product__name", "purchase__supplier__name")
            .annotate(
                qty_bought=Sum("quantity"),
                total_cost=Sum(F("quantity") * F("unit_cost_price")),
                avg_unit_cost=Avg("unit_cost_price"),
            )
            .order_by("-total_cost")[:10]
        )

        top_purchases = [
            {
                "name": item["product__name"],
                "supplier": {"name": item.get("purchase__supplier__name") or "—"},
                "qty_bought": item["qty_bought"],
                "total_cost": item["total_cost"],
                "avg_unit_cost": item["avg_unit_cost"] or Decimal("0.00"),
            }
            for item in top_purchases_qs
        ]

        recent_purchases = purchases_qs.order_by("-purchase_date")[:20].select_related("supplier")

        recent_purchases_list = [
            {
                "id": p.id,
                "purchase_date": p.purchase_date,
                "supplier": {"name": p.supplier.name if p.supplier else "—"},
                "total_cost": p.total_amount,
                "status": p.payment_status or "PENDING",          # template expects .status
                "payment_status": p.payment_status or "—",
            }
            for p in recent_purchases
        ]

        context.update({
            "metrics": {
                "Total Purchase Cost": f"KES {agg['total_cost']:,.2f}",
                "Purchase Transactions": agg["purchase_count"],
            },
            "metrics_items": [
                ["Total Purchase Cost", f"KES {agg['total_cost']:,.2f}"],
                ["Purchase Transactions", agg["purchase_count"]],
            ],
            "top_purchases": top_purchases,
            "recent_purchases": recent_purchases_list,
            "filters_form": filterset.form,
        })

    # ========================= EXPENSES REPORT =========================
    elif report_type == "expenses":
        context["title"] = "Expenses Report"

        filterset = ExpenseReportFilter(
            request.GET or None, queryset=scoped_qs(Expense)
        )
        if not request.GET.get("date_range_after") and not request.GET.get("date_range_before"):
            filterset.form.initial["date_range"] = {
                "gte": default_start.date(),
                "lte": default_end.date(),
            }

        expenses_qs = filterset.qs

        agg = expenses_qs.aggregate(
            total_expense=Sum("amount", default=Decimal("0.00")),
            count=Count("id"),
        )

        by_type_qs = (
            expenses_qs.values("expense_type")
            .annotate(total=Sum("amount"))
            .order_by("-total")
        )

        total_all = agg["total_expense"] or Decimal("1")
        expense_by_category = []
        for b in by_type_qs:
            count = expenses_qs.filter(expense_type=b["expense_type"]).count()
            perc = round((b["total"] / total_all * 100), 1)
            expense_by_category.append({
                "name": b["expense_type"],
                "count": count,
                "total": b["total"],
                "percentage": perc,
            })

        recent_expenses = expenses_qs.order_by("-date")[:20].select_related("incurred_by")
        recent_expenses_list = [
            {
                "id": e.id,
                "expense_date": e.date,                  # template expects expense_date
                "description": e.title,
                "category": {"name": e.expense_type},    # template expects .category.name
                "amount": e.amount,
                "paid_by": e.incurred_by,                # has .full_name
            }
            for e in recent_expenses
        ]

        context.update({
            "metrics": {
                "Total Expenses": f"KES {agg['total_expense']:,.2f}",
                "Expense Entries": agg["count"],
            },
            "metrics_items": [
                ["Total Expenses", f"KES {agg['total_expense']:,.2f}"],
                ["Expense Entries", agg["count"]],
            ],
            "expense_by_category": expense_by_category,
            "recent_expenses": recent_expenses_list,
            "filters_form": filterset.form,
        })

    # ========================= STOCK REPORT =========================
    elif report_type == "stock":
        context["title"] = "Stock Report"

        stock_qs = scoped_qs(Stock).select_related("product", "product__category")

        low_stock_qs = stock_qs.filter(quantity__lte=F("product__reorder_level"))
        zero_stock_qs = stock_qs.filter(quantity=0)

        total_value = stock_qs.aggregate(
            value=Sum(F("quantity") * F("product__average_cost_price"), default=Decimal("0.00"))
        )["value"]

        # Enrich for stock_print.html
        stock_items = []
        for s in stock_qs:
            stock_items.append({
                "name": s.product.name,
                "category": {"name": getattr(s.product.category, "name", "—")},
                "current_stock": s.quantity,
                "available_quantity": s.quantity,
                "stock_value": s.quantity * (s.product.average_cost_price or Decimal("0")),
                "reorder_level": s.product.reorder_level,
            })

        low_stock_items = []
        for s in low_stock_qs:
            low_stock_items.append({
                "name": s.product.name,
                "category": {"name": getattr(s.product.category, "name", "—")},
                "current_stock": s.quantity,
                "reorder_level": s.product.reorder_level,
                "stock_value": s.quantity * (s.product.average_cost_price or Decimal("0")),
            })

        context.update({
            "metrics": {
                "Current Stock Value (at avg cost)": f"KES {total_value:,.2f}",
                "Low Stock Items": low_stock_qs.count(),
                "Out of Stock Items": zero_stock_qs.count(),
            },
            "metrics_items": [
                ["Current Stock Value", f"KES {total_value:,.2f}"],
                ["Low Stock Items", low_stock_qs.count()],
                ["Out of Stock Items", zero_stock_qs.count()],
            ],
            "stock_items": stock_items,
            "low_stock_items": low_stock_items,
        })

    else:
        return HttpResponse("Invalid report type", status=400)

    # ========================= PDF EXPORT =========================
    if request.GET.get("export") == "pdf":
        from weasyprint import HTML
        # Use correct template name (your provided files)
        template_name = {
            "sales": "sales_print.html",
            "stock": "stock_print.html",
            "purchases": "purchase_print.html",
            "expenses": "expenses_print.html",
        }.get(report_type, f"{report_type}_print.html")

        html_content = render(request, f"reports/{template_name}", context).content.decode("utf-8")
        pdf = HTML(string=html_content).write_pdf()

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{report_type}_report_{now.strftime("%Y-%m-%d")}.pdf"'
        )
        return response

    # Web view (base_report.html + any extended template like sales.html)
    return render(request, "reports/base_report.html", context)