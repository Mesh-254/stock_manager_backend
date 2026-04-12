"""

Dashboard callback function that provides data for the admin dashboard.

This function is called by the admin index view and returns a context dictionary

containing all the data needed to render the dashboard: KPI cards, charts, and tables.

Usage in settings.py:

    UNFOLD = {

        'DASHBOARD_CALLBACK': 'backend.utils.dashboard.dashboard_callback',

        # ... other Unfold settings

    }

"""

from django.utils import timezone

from django.db.models import Sum, Count, Q, F

from django.db.models.functions import TruncDate, Coalesce

from datetime import timedelta

from decimal import Decimal

import json


def dashboard_callback(request, extra_context=None):
    """

    Main dashboard callback that processes request parameters and returns

    context data for the admin dashboard.



    Parameters:

        request: HttpRequest object

        extra_context: Optional initial context dictionary



    Returns:

        Dictionary containing dashboard data for template rendering

    """

    extra_context = extra_context or {}

    # Determine if user is superadmin (for global vs shop-scoped view)

    is_superadmin = request.user.is_superuser

    # Get date range from request (POST during HTMX, GET on initial load)

    from_date_str = request.POST.get("from_date") or request.GET.get("from_date")

    to_date_str = request.POST.get("to_date") or request.GET.get("to_date")

    # Set default date range (current month)

    today = timezone.now().date()

    if not from_date_str:

        from_date = today.replace(day=1)

    else:

        from_date = timezone.datetime.strptime(from_date_str, "%Y-%m-%d").date()

    if not to_date_str:

        to_date = today

    else:

        to_date = timezone.datetime.strptime(to_date_str, "%Y-%m-%d").date()

    # Import models (assumes you have these in shop_manager app)

    from shop_manager.models import Usage, Stock, StockTransaction, Purchase, Product, Expense, DailyStudentRecord

    # Filter by shop if not superadmin

    user_shop = getattr(request.user, "shop", None) if not is_superadmin else None

    # Build base queryset filters

    # Base querysets with proper shop scoping
    if user_shop:
        usage_qs = Usage.objects.filter(shop=user_shop, usage_date__range=[from_date, to_date])
        purchase_qs = Purchase.objects.filter(shop=user_shop, purchase_date__range=[from_date, to_date])
        expense_qs = Expense.objects.filter(shop=user_shop, date__range=[from_date, to_date])
        stock_qs = Stock.objects.filter(product__shop=user_shop)
        transaction_qs = StockTransaction.objects.filter(
            stock__product__shop=user_shop, created_at__date__range=[from_date, to_date]
        )
    else:
        usage_qs = Usage.objects.filter(usage_date__range=[from_date, to_date])
        purchase_qs = Purchase.objects.filter(purchase_date__range=[from_date, to_date])
        expense_qs = Expense.objects.filter(date__range=[from_date, to_date])
        stock_qs = Stock.objects.all()
        transaction_qs = StockTransaction.objects.filter(created_at__date__range=[from_date, to_date])
        
    # ===== KPI CARDS =====

    total_usage_cost = usage_qs.aggregate(
        total=Coalesce(Sum("total_cost"), Decimal("0"))
    )["total"]

    total_purchases = purchase_qs.aggregate(
        total=Coalesce(Sum("total_amount"), Decimal("0"))
    )["total"]

    total_expense = expense_qs.aggregate(
        total=Coalesce(Sum("amount"), Decimal("0"))
    )["total"]

    total_cost = total_usage_cost + total_expense

    product_count = (
        Product.objects.filter(shop=user_shop).count()
        if user_shop
        else Product.objects.count()
    )

    low_stock_count = stock_qs.filter(

        quantity__lte=F("product__reorder_level")

    ).count()

    # Add after getting user_shop and before cards = [...]

    # Today's students present
    today = timezone.now().date()
    today_students = 0
    if user_shop:
        today_record = DailyStudentRecord.objects.filter(
            shop=user_shop, record_date=today
        ).first()
        today_students = today_record.students_present if today_record else 0
    else:
        # For SuperAdmin - show total across all shops (optional)
        today_students = DailyStudentRecord.objects.filter(
            record_date=today
        ).aggregate(total=Sum("students_present"))["total"] or 0

    cards = [
        {
            "title": "Total Usage Cost",
            "value": f"KES {total_cost:,.0f}",
            "subtitle": f"{usage_qs.count()} entries",
            "url": "/admin/shop_manager/usage/",
            "icon": "trending-down",
            "color": "red",
        },
        {
            "title": "Total Purchases",
            "value": f"KES {total_purchases:,.0f}",
            "subtitle": f"{purchase_qs.count()} purchases",
            "url": "/admin/shop_manager/purchase/",
            "icon": "shopping-cart",
            "color": "green",
        },
        {
            "title": "Products",
            "value": str(product_count),
            "subtitle": f"Managed items",
            "url": "/admin/shop_manager/product/",
            "icon": "package",
            "color": "blue",
        },
        {
            "title": "Low Stock Items",
            "value": str(low_stock_count),
            "subtitle": "Need reorder",
            "url": "/admin/shop_manager/stock/?quantity__lt=reorder_level",
            "icon": "alert-circle",
            "color": "amber",
        },
        {
            "title": "Students Present Today",
            "value": str(today_students),
            "subtitle": f"Recorded on {today.strftime('%d %b')}",
            "url": "/admin/shop_manager/dailystudentrecord/",
            "icon": "group",
            "color": "indigo",          # or "blue", "purple"
        },
    ]

    # ===== RECENT USAGES (Last 5) =====

    recent_usages = usage_qs.select_related("recorded_by").order_by("-usage_date")[:5]

    # ===== LOW STOCK ALERTS =====

    low_stock_alerts = stock_qs.filter(
        quantity__lte=F("product__reorder_level")
    ).select_related("product", "product__category").order_by("quantity")[:6]

    # ===== RECENT TRANSACTIONS (Last 10) =====

    recent_transactions = transaction_qs.select_related(
        "stock", "stock__product", "created_by"
    ).order_by("-created_at")[:10]

    # ===== USAGE TREND (Last 30 days) =====

    thirty_days_ago = today - timedelta(days=30)

    usage_trend = list(
        usage_qs.filter(usage_date__gte=thirty_days_ago)   # Correct: usage_date, not usage__date
        .annotate(date=TruncDate("usage_date"))
        .values("date")
        .annotate(daily_cost=Coalesce(Sum("total_cost"), Decimal("0")))
        .order_by("date")
    )
    # Convert to JSON-safe format

    usage_trend_json = json.dumps(
        [
            {
                "usage_date": str(item["date"]),
                "daily_cost": float(item["daily_cost"]),
            }
            for item in usage_trend
        ]
    )

    # ===== STOCK BY CATEGORY =====

    stock_by_category = list(
        stock_qs.values("product__category__name")
        .annotate(value=Coalesce(
            Sum(F("quantity") * F("product__average_cost_price")), Decimal("0")
        ))
        .order_by("-value")
    )

    # Convert to JSON-safe format

    stock_by_category_json = json.dumps(
        [
            {
                "product__category__name": item["product__category__name"],
                "value": float(item["value"]),
            }
            for item in stock_by_category
        ]
    )

    # ===== BUILD CONTEXT =====

    extra_context.update(
        {
            "cards": cards,
            "recent_usages": recent_usages,
            "low_stock_alerts": low_stock_alerts,
            "recent_transactions": recent_transactions,
            "usage_trend": usage_trend_json,
            "stock_by_category": stock_by_category_json,
            "show_date_filter": True,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "current_month": today.strftime("%B %Y"),
            "is_superadmin": is_superadmin,
        }
    )

    return extra_context
