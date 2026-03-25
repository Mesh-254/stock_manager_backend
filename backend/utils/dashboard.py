"""
Dashboard Callback for UNFOLD Admin Dashboard

Provides dynamic KPI cards and context for the school shop inventory dashboard.
"""

from datetime import timedelta, datetime
from decimal import Decimal

from django.db.models import Sum, F
from django.utils import timezone
from django.urls import reverse

from accounts.models import UserRole
from shop_manager.models import Usage, UsageItem, Purchase, Stock, StockTransaction


def dashboard_callback(request, context):
    """
    Unfold dashboard callback.
    Must accept (request, context) and return the (updated) context dict.
    """
    now = timezone.now()
    today = now.date()
    thirty_days_ago = now - timedelta(days=30)

    user = request.user

    # Early exit for ShopAdmin without assigned shop
    if user.role == UserRole.SHOP_ADMIN and not getattr(user, "shop", None):
        context["cards"] = []
        context["error"] = "No shop assigned to your account."
        return context

    # Scoped queryset helper
    def scoped(queryset):
        qs = queryset
        if user.role == UserRole.SUPER_ADMIN:
            return qs
        if user.role == UserRole.SHOP_ADMIN and user.shop:
            if hasattr(qs.model, "shop"):
                return qs.filter(shop=user.shop)
            elif qs.model == UsageItem:
                return qs.filter(usage__shop=user.shop)
            elif qs.model == Stock:
                return qs.filter(product__shop=user.shop)
        return qs.none()

    # Date range from GET params (for custom filtering on the dashboard)
    from_date_str = request.GET.get("from_date")
    to_date_str = request.GET.get("to_date")

    from_date = None
    to_date = None
    if from_date_str:
        try:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    if to_date_str:
        try:
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    chart_start = from_date if from_date else thirty_days_ago.date()
    chart_end = to_date if to_date else today

    # ─── Core Aggregations ─────────────────────────────────────────────
    usage_qs = scoped(Usage.objects.all())
    usage_items_qs = scoped(UsageItem.objects.all())

    if from_date or to_date:
        usage_qs = usage_qs.filter(
            usage_date__gte=chart_start, usage_date__lte=chart_end
        )
        usage_items_qs = usage_items_qs.filter(
            usage__usage_date__gte=chart_start, usage__usage_date__lte=chart_end
        )

    total_usage_cost = usage_qs.aggregate(total=Sum("total_cost"))["total"] or Decimal(
        "0.00"
    )

    this_month_start = now.replace(day=1).date()
    this_month_usage = usage_qs.filter(usage_date__gte=this_month_start).aggregate(
        total=Sum("total_cost")
    )["total"] or Decimal("0.00")

    total_purchase_cost = scoped(Purchase.objects.all()).aggregate(
        total=Sum("total_amount")
    )["total"] or Decimal("0.00")

    stock_qs = scoped(Stock.objects.select_related("product"))
    inventory_cost_value = stock_qs.aggregate(
        value=Sum(F("quantity") * F("product__average_cost_price"))
    )["value"] or Decimal("0.00")

    low_stock_count = stock_qs.filter(
        quantity__lte=F("product__reorder_level"), quantity__gt=0
    ).count()

    out_of_stock_count = stock_qs.filter(quantity=0).count()

    # ─── KPI Cards ─────────────────────────────────────────────────────
    cards = [
        {
            "title": "Total Usage Cost",
            "value": f"KES {total_usage_cost:,.2f}",
            "subtitle": f"This month: KES {this_month_usage:,.2f}",
            "color": "danger",
            "icon": "trending_down",
            "url": reverse("admin:shop_manager_usage_changelist"),
        },
        {
            "title": "Total Purchase Cost",
            "value": f"KES {total_purchase_cost:,.2f}",
            "subtitle": "All purchases recorded",
            "color": "success",
            "icon": "shopping_cart",
            "url": reverse("admin:shop_manager_purchase_changelist"),
        },
        {
            "title": "Stock Value (Avg Cost)",
            "value": f"KES {inventory_cost_value:,.2f}",
            "subtitle": "Current inventory valuation",
            "color": "amber",
            "icon": "inventory_2",
            "url": reverse("admin:shop_manager_stock_changelist"),
        },
        {
            "title": "Stock Alerts",
            "value": f"{low_stock_count} low • {out_of_stock_count} out",
            "subtitle": "Items needing attention",
            "color": "warning" if low_stock_count > 0 else "secondary",
            "icon": "warning_amber",
            "url": reverse("admin:shop_manager_stock_changelist"),
        },
    ]

    # ─── Recent Activity ───────────────────────────────────────────────
    recent_usages = (
        usage_qs.select_related("recorded_by")
        .prefetch_related("items__product")
        .order_by("-usage_date")[:8]
    )

    recent_low_stock = (
        stock_qs.filter(quantity__lte=F("product__reorder_level"))
        .select_related("product", "product__category")
        .order_by("quantity")[:6]
    )

    recent_transactions = scoped(
        StockTransaction.objects.select_related("stock__product", "created_by")
    ).order_by("-created_at")[:8]

    # ─── Update Context ─────────────────────────────────────────────────
    context.update(
        {
            "cards": cards,
            "recent_usages": recent_usages,
            "low_stock_alerts": recent_low_stock,
            "recent_transactions": recent_transactions,
            "show_date_filter": True,
            "from_date": from_date_str,
            "to_date": to_date_str,
            "current_month": now.strftime("%B %Y"),
            "is_superadmin": user.role == UserRole.SUPER_ADMIN,
        }
    )

    return context
