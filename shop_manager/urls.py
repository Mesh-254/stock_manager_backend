# shop_manager/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path, include

from . import views
from .report_views import report_view
from .custom_views import (
    add_purchase_view,
    add_usage_view,
    detail_purchase_view,
    detail_usage_view,
    edit_purchase_view,
    edit_usage_view,
)

router = DefaultRouter()

router.register(r"shops", views.ShopViewSet, basename="shop")
router.register(r"categories", views.CategoryViewSet, basename="category")
router.register(r"suppliers", views.SupplierViewSet, basename="supplier")
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"stocks", views.StockViewSet, basename="stock")
router.register(
    r"stock-transactions", views.StockTransactionViewSet, basename="stock-transaction"
)
router.register(r"purchases", views.PurchaseViewSet, basename="purchase")
router.register(r"purchaseitems", views.PurchaseItemViewSet, basename="purchaseitem")
router.register(r"usages", views.UsageViewSet, basename="usage")  # changed from "sales"
router.register(r"usageitems", views.UsageItemViewSet, basename="usageitem")

urlpatterns = [
    path("", include(router.urls)),
    path("reports/<str:report_type>/", report_view, name="report_view"),
    # Custom template-based views
    path("add-purchase/", add_purchase_view, name="add_purchase_custom"),
    path("edit-purchase/<uuid:purchase_id>/", edit_purchase_view, name="edit_purchase"),
    path(
        "detail-purchase/<uuid:purchase_id>/",
        detail_purchase_view,
        name="detail_purchase",
    ),
    path("add-usage/", add_usage_view, name="add_usage_custom"),
    path("edit-usage/<uuid:usage_id>/", edit_usage_view, name="edit_usage"),
    path("detail-usage/<uuid:usage_id>/", detail_usage_view, name="detail_usage"),
]
