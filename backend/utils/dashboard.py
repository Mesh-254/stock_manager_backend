# shop_manager/dashboard.py
"""
Enhanced dashboard callback for Unfold admin.
Features:
- Full role-based scoping (SuperAdmin vs ShopAdmin)
- Custom date range filtering via GET params (from_date / to_date)
- Accurate key metrics using SaleItem snapshots for COGS (unit_cost_price)
- Dual inventory valuation: selling price & cost price
- Efficient queries with proper annotations and aggregations
- Trend data for revenue & gross profit (last 30 days or custom range)
- Top 10 selling brands by revenue
- Recent sales, low stock alerts, and recent stock transactions
- All values in KES with proper formatting
"""

import json
from datetime import timedelta, datetime
from decimal import Decimal

from django.db.models import Sum, Count, F, Q, Value, DecimalField, DateField
from django.db.models.functions import TruncDate, Coalesce
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages

from accounts.models import User, UserRole
from shop_manager.models import (
    Shop,
    Product,
    Stock,
    Sale,
    SaleItem,
    Purchase,
    Expense,
    StockTransaction,
)


def get_filtered_qs(request, queryset):
    """
    Apply role-based scoping to any queryset.
    - SuperAdmin: full access
    - ShopAdmin: only their shop (direct + nested relationships)
    - Others: empty
    """
    user = request.user

    if user.role == UserRole.SUPER_ADMIN:
        return queryset

    if user.role != UserRole.SHOP_ADMIN or not user.shop:
        return queryset.none()

    model = queryset.model

    # Direct shop field
    if hasattr(model, "shop"):
        return queryset.filter(shop=user.shop)

    # Nested relationships
    if model == Stock:
        return queryset.filter(product__shop=user.shop)
    if model == SaleItem:
        return queryset.filter(sale__shop=user.shop)
    if model == StockTransaction:
        return queryset.filter(stock__product__shop=user.shop)

    return queryset.none()


def dashboard_callback(request, context=None):
    """
    Main dashboard context processor.
    Returns all data needed for a professional, accurate dashboard.
    """
    now = timezone.now()
    today = now.date()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    user = request.user

    # Early exit if ShopAdmin has no shop assigned
    if user.role == UserRole.SHOP_ADMIN and not user.shop:
        messages.warning(
            request, "Your account is not assigned to any shop. Contact support."
        )
        return {
            "cards": [],
            "recent_sales": [],
            "low_stock_alerts": [],
            "recent_transactions": [],
            "show_date_filter": False,
            "error": "No shop assigned",
        }

    # Helper for scoped querysets
    def filtered(qs):
        return get_filtered_qs(request, qs)

    # ─── Date Range Handling ─────────────────────────────────────────────
    from_date_str = request.GET.get("from_date")
    to_date_str = request.GET.get("to_date")

    from_date = None
    to_date = None

    if from_date_str:
        try:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        except ValueError:
            from_date = None

    if to_date_str:
        try:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
            to_date += timedelta(
                days=1
            )  # Make query inclusive (up to end of selected day)
        except ValueError:
            to_date = None

    # Chart range: custom if provided, else last 30 days
    chart_start = (
        datetime.combine(from_date, datetime.min.time())
        if from_date
        else thirty_days_ago
    )
    chart_end = (
        datetime.combine(to_date, datetime.max.time()) if to_date else now
    )  # ← Fixed: no .date()
    # Filter SaleItem for calculations (most accurate source)
    sale_items_qs = filtered(SaleItem.objects.all())
    if from_date or to_date:
        sale_items_qs = sale_items_qs.filter(
            sale__sale_date__gte=chart_start,
            sale__sale_date__lt=chart_end if to_date else Q(),
        )

    # ─── Core Aggregations (All-time unless specified) ───────────────────
    # Revenue & Gross Profit (using SaleItem snapshots)
    profit_agg = sale_items_qs.aggregate(
        total_revenue=Coalesce(
            Sum(F("quantity") * F("unit_selling_price")), Decimal("0.00")
        ),
        total_cogs=Coalesce(Sum(F("quantity") * F("unit_cost_price")), Decimal("0.00")),
    )
    total_revenue = profit_agg["total_revenue"]
    total_gross_profit = profit_agg["total_revenue"] - profit_agg["total_cogs"]
    gross_margin = (
        (total_gross_profit / total_revenue * 100)
        if total_revenue > 0
        else Decimal("0.0")
    )

    # This month specifics
    this_month_items = filtered(
        SaleItem.objects.filter(sale__sale_date__gte=this_month_start)
    )
    this_month_agg = this_month_items.aggregate(
        revenue=Coalesce(Sum(F("quantity") * F("unit_selling_price")), Decimal("0.00")),
        count=Count("sale", distinct=True),
    )
    revenue_this_month = this_month_agg["revenue"]
    sales_this_month_count = filtered(
        Sale.objects.filter(sale_date__gte=this_month_start)
    ).count()
    avg_order_value = (
        revenue_this_month / sales_this_month_count
        if sales_this_month_count > 0
        else Decimal("0.00")
    )
    # Net Profit (last 30 days): Revenue - Expenses
    expenses_30d = filtered(
        Expense.objects.filter(date__gte=thirty_days_ago.date())
    ).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
    net_profit_30d = (revenue_this_month or Decimal("0.00")) - expenses_30d

    # Inventory Valuation
    stock_qs = filtered(Stock.objects.select_related("product"))
    inventory_selling = stock_qs.aggregate(
        value=Coalesce(
            Sum(F("quantity") * F("product__selling_price")), Decimal("0.00")
        )
    )["value"]

    inventory_cost = stock_qs.aggregate(
        value=Coalesce(
            Sum(F("quantity") * F("product__average_cost_price")), Decimal("0.00")
        )
    )["value"]

    # Low / Out of Stock
    low_stock_qs = stock_qs.filter(quantity__lte=F("product__reorder_level"))
    low_stock_count = low_stock_qs.count()
    out_of_stock_count = stock_qs.filter(quantity=0).count()

    # Total sales count (all-time)
    total_sales_count = filtered(Sale.objects.all()).count()

    # ─── Chart Data: Daily Revenue & Gross Profit Trend ──────────────────
    daily_trend = (
        filtered(
            SaleItem.objects.filter(
                sale__sale_date__gte=chart_start, sale__sale_date__lt=chart_end
            )
        )
        .annotate(date=TruncDate("sale__sale_date"))
        .values("date")
        .annotate(
            revenue=Coalesce(
                Sum(F("quantity") * F("unit_selling_price")), Decimal("0.00")
            ),
            cogs=Coalesce(Sum(F("quantity") * F("unit_cost_price")), Decimal("0.00")),
        )
        .order_by("date")
    )

    # Define inclusive end date
    if to_date:
        end_date = to_date - timedelta(days=1)  # to_date is already +1 day
    else:
        end_date = today  # Include today when no custom range

    # Fill missing dates for continuous chart
    trend_dates = []
    trend_revenue = []
    trend_profit = []
    current_date = chart_start.date()
    daily_dict = {item["date"]: item for item in daily_trend}

    while current_date <= end_date:
        data = daily_dict.get(
            current_date, {"revenue": Decimal("0.00"), "cogs": Decimal("0.00")}
        )
        trend_dates.append(current_date.strftime("%b %d"))  # Nice format: "Feb 12"
        trend_revenue.append(float(data["revenue"]))
        trend_profit.append(float(data["revenue"] - data["cogs"]))
        current_date += timedelta(days=1)

    # ─── Top 10 Selling Categories by Revenue (chart period) ─────────────────
    top_categories = (
        filtered(
            SaleItem.objects.filter(
                sale__sale_date__gte=chart_start, sale__sale_date__lt=chart_end
            )
        )
        .values(category_name=F("product__category__name"))
        .annotate(
            revenue=Coalesce(
                Sum(F("quantity") * F("unit_selling_price")), Decimal("0.00")
            )
        )
        .order_by("-revenue")[:10]
    )

    category_names = json.dumps(
        [item.get("category_name") or "Uncategorized" for item in top_categories]
    )
    category_values = json.dumps([float(item["revenue"]) for item in top_categories])

    # ─── Recent Activity ─────────────────────────────────────────────────
    recent_sales = (
        filtered(Sale.objects.select_related("sold_by"))
        .prefetch_related(
            "items__product",
            "items__product__category",
        )
        .annotate(
            items_count=Count("items")  # or Count(SaleItem.sale.rel.related_name)
        )
        .order_by("-sale_date")[:8]
    )

    recent_low_stock = (
        stock_qs.filter(quantity__lte=F("product__reorder_level"))
        .select_related("product", "product__category")
        .order_by("quantity")[:8]
        .values("product__name", "quantity", "product__category__name")
    )

    recent_transactions = (
        filtered(
            StockTransaction.objects.select_related("stock__product", "created_by")
        )
        .order_by("-created_at")[:10]
        .values(
            "stock__product__name",
            "quantity_change",
            "type",
            "reason",
            "created_at",
            "created_by__full_name",
        )
    )

    # ─── KPI Cards ───────────────────────────────────────────────────────
    cards = [
        {
            "title": "Total Revenue",
            "value": f"KES {total_revenue:,.2f}",
            "subtitle": f"This month: KES {revenue_this_month:,.2f}",
            "color": "emerald",
            "icon": "payments",
            "url": reverse("admin:shop_manager_sale_changelist"),
        },
        {
            "title": "Gross Profit",
            "value": f"KES {total_gross_profit:,.2f}",
            "subtitle": "Revenue − COGS (at sale-time cost)",
            "color": "emerald" if total_gross_profit > 0 else "danger",
            "icon": "trending_up",
            "url": reverse("admin:shop_manager_sale_changelist"),
        },
        {
            "title": "Gross Margin",
            "value": f"{gross_margin:.1f}%",
            "subtitle": "Gross Profit / Revenue",
            "color": "blue",
            "icon": "percent",
        },
        {
            "title": "Net Profit (30d)",
            "value": f"KES {net_profit_30d:,.2f}",
            "subtitle": "Revenue − Expenses (last 30 days)",
            "color": "emerald" if net_profit_30d > 0 else "danger",
            "icon": "account_balance_wallet",
            "url": reverse("admin:shop_manager_expense_changelist"),
        },
        {
            "title": "Average Order Value",
            "value": f"KES {avg_order_value:,.2f}",
            "subtitle": "This month",
            "color": "info",
            "icon": "calculate",
            "url": reverse("admin:shop_manager_sale_changelist"),
        },
        {
            "title": "Inventory Value (Selling)",
            "value": f"KES {inventory_selling:,.2f}",
            "subtitle": "Current stock at selling price",
            "color": "secondary",
            "icon": "inventory_2",
            "url": reverse("admin:shop_manager_stock_changelist"),
        },
        {
            "title": "Inventory Value (Cost)",
            "value": f"KES {inventory_cost:,.2f}",
            "subtitle": "Current stock at average cost",
            "color": "amber",
            "icon": "account_balance",
            "url": reverse("admin:shop_manager_stock_changelist"),
        },
        {
            "title": "Stock Alerts",
            "value": str(low_stock_count),
            "subtitle": f"Out of stock: {out_of_stock_count}",
            "color": "warning" if low_stock_count > 0 else "secondary",
            "icon": "warning_amber",
            "url": f"{reverse('admin:shop_manager_stock_changelist')}?quantity__lte=10",  # Consider custom filter for reorder_level
            "help_text": "Items at or below reorder level",
        },
    ]

    # ─── Final Context ───────────────────────────────────────────────────
    extra_context = {
        "cards": cards,
        "recent_sales": recent_sales,
        "low_stock_alerts": recent_low_stock,
        "recent_transactions": recent_transactions,
        "show_date_filter": True,
        "current_month": now.strftime("%B %Y"),
        "user_role": user.role,
        "is_superadmin": user.role == UserRole.SUPER_ADMIN,
        # Chart data
        "chart_dates": json.dumps(trend_dates),
        "chart_revenue": json.dumps(trend_revenue),
        "chart_profit": json.dumps(trend_profit),
        "category_names": json.dumps(category_names),
        "category_values": json.dumps(category_values),
        # For header display
        "from_date": from_date_str,
        "to_date": (
            (to_date - timedelta(days=1)).strftime("%Y-%m-%d") if to_date else None
        ),
    }

    if context is not None:
        context.update(extra_context)

    return context
