"""
Dashboard callback – FIXED & OPTIMIZED (2026 production ready)
- True all-time support on Reset
- Proper shop scoping for SuperAdmin vs ShopAdmin
- Efficient aggregates + select_related
- JSON keys fixed for both templates
"""

from django.utils import timezone
from django.db.models import Sum, Count, F
from django.db.models.functions import Coalesce, TruncDate
from decimal import Decimal
import json
from datetime import timedelta


def dashboard_callback(request, extra_context=None):
    extra_context = extra_context or {}

    is_superadmin = getattr(request.user, "role", None) == "SuperAdmin" or request.user.is_superuser
    user_shop = getattr(request.user, "shop", None) if not is_superadmin else None

    # ====================== DATE FILTER LOGIC ======================
    from_date_str = request.POST.get("from_date") or request.GET.get("from_date") or ""
    to_date_str = request.POST.get("to_date") or request.GET.get("to_date") or ""

    today = timezone.now().date()
    all_time = False
    from_date = None
    to_date = None

    if from_date_str and to_date_str:
        from_date = timezone.datetime.strptime(from_date_str, "%Y-%m-%d").date()
        to_date = timezone.datetime.strptime(to_date_str, "%Y-%m-%d").date()
    elif request.method == "POST" and not from_date_str and not to_date_str:
        all_time = True  # Reset button → ALL TIME
    else:
        # Initial load → current month
        from_date = today.replace(day=1)
        to_date = today

    # ====================== BASE QUERIES (shop-scoped) ======================
    from shop_manager.models import (
        Usage, Purchase, Expense, Stock, StockTransaction,
        Product, DailyStudentRecord
    )

    if user_shop:
        base_usage = Usage.objects.filter(shop=user_shop)
        base_purchase = Purchase.objects.filter(shop=user_shop)
        base_expense = Expense.objects.filter(shop=user_shop)
        base_stock = Stock.objects.filter(product__shop=user_shop)
        base_transaction = StockTransaction.objects.filter(stock__product__shop=user_shop)
    else:
        base_usage = Usage.objects.all()
        base_purchase = Purchase.objects.all()
        base_expense = Expense.objects.all()
        base_stock = Stock.objects.all()
        base_transaction = StockTransaction.objects.all()

    # Apply date filter only when not all-time
    if all_time:
        usage_qs = base_usage
        purchase_qs = base_purchase
        expense_qs = base_expense
        transaction_qs = base_transaction
    else:
        usage_qs = base_usage.filter(usage_date__range=[from_date, to_date])
        purchase_qs = base_purchase.filter(purchase_date__range=[from_date, to_date])
        expense_qs = base_expense.filter(date__range=[from_date, to_date])
        transaction_qs = base_transaction.filter(created_at__date__range=[from_date, to_date])

    # ====================== KPI CARDS ======================
    total_usage_cost = usage_qs.aggregate(total=Coalesce(Sum("total_cost"), Decimal("0")))["total"]
    total_purchases = purchase_qs.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0")))["total"]
    total_expense = expense_qs.aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"]
    total_cost = total_usage_cost + total_expense

    product_count = Product.objects.filter(shop=user_shop).count() if user_shop else Product.objects.count()
    low_stock_count = base_stock.filter(quantity__lte=F("product__reorder_level")).count()

    # Today's students
    today_students = 0
    if user_shop:
        record = DailyStudentRecord.objects.filter(shop=user_shop, record_date=today).first()
        today_students = record.students_present if record else 0
    else:
        today_students = DailyStudentRecord.objects.filter(record_date=today).aggregate(
            total=Coalesce(Sum("students_present"), 0)
        )["total"]

    cards = [
        {"title": "Total Usage Cost", "value": f"KES {total_cost:,.0f}", "subtitle": f"{usage_qs.count()} entries", "url": "/admin/shop_manager/usage/"},
        {"title": "Total Purchases", "value": f"KES {total_purchases:,.0f}", "subtitle": f"{purchase_qs.count()} purchases", "url": "/admin/shop_manager/purchase/"},
        {"title": "Products", "value": str(product_count), "subtitle": "Managed items", "url": "/admin/shop_manager/product/"},
        {"title": "Low Stock Items", "value": str(low_stock_count), "subtitle": "Need reorder", "url": "/admin/shop_manager/stock/"},
        {"title": "Students Present Today", "value": str(today_students), "subtitle": f"Recorded on {today.strftime('%d %b')}", "url": "/admin/shop_manager/dailystudentrecord/"},
    ]

    # ====================== RECENT + ALERTS ======================
    recent_usages = usage_qs.select_related("recorded_by").order_by("-usage_date")[:5]
    low_stock_alerts = base_stock.filter(quantity__lte=F("product__reorder_level")).select_related("product", "product__category").order_by("quantity")[:6]
    recent_transactions = transaction_qs.select_related("stock__product", "created_by").order_by("-created_at")[:10]

    # ====================== CHARTS ======================
    # Usage trend – always last 30 days (UI friendly)
    thirty_days_ago = today - timedelta(days=30)
    trend_qs = base_usage.filter(usage_date__gte=thirty_days_ago)
    usage_trend = list(
        trend_qs.annotate(date=TruncDate("usage_date"))
        .values("date")
        .annotate(daily_cost=Coalesce(Sum("total_cost"), Decimal("0")))
        .order_by("date")
    )
    usage_trend_json = json.dumps([
        {"usage_date": str(item["date"]), "daily_cost": float(item["daily_cost"])}
        for item in usage_trend
    ])

    # Stock by category (current value)
    stock_by_category = list(
        base_stock.annotate(category_name=F("product__category__name"))
        .values("category_name")
        .annotate(value=Coalesce(Sum(F("quantity") * F("product__average_cost_price")), Decimal("0")))
        .order_by("-value")
    )
    stock_by_category_json = json.dumps([
        {"category__name": item["category_name"] or "Unknown", "value": float(item["value"])}
        for item in stock_by_category
    ])

    # ====================== FINAL CONTEXT ======================
    extra_context.update({
        "cards": cards,
        "recent_usages": recent_usages,
        "low_stock_alerts": low_stock_alerts,
        "recent_transactions": recent_transactions,
        "usage_trend": usage_trend_json,
        "stock_by_category": stock_by_category_json,
        "show_date_filter": True,
        "from_date": "" if all_time else (from_date.isoformat() if from_date else ""),
        "to_date": "" if all_time else (to_date.isoformat() if to_date else ""),
        "current_month": "All Time" if all_time else today.strftime("%B %Y"),
        "is_superadmin": is_superadmin,
    })

    return extra_context