from rest_framework.routers import DefaultRouter
from django.urls import path, include
from shop_manager import views
from shop_manager.report_views import report_view
from .custom_views import (
    add_purchase_view,
    add_usage_view,
    detail_purchase_view,
    detail_usage_view,
    edit_purchase_view,
    edit_usage_view,
)


# Create a router and register our viewset with it.
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
router.register(r"sales", views.UsageViewSet, basename="sale")
router.register(r"saleitems", views.UsageItemViewSet, basename="saleitem")


urlpatterns = [
    path("", include(router.urls)),
    path("reports/<str:report_type>/", report_view, name="report_view"),
    # Custom views for purchase and sale management
    path("add-purchase/", add_purchase_view, name="add_purchase_custom"),
    path("edit-purchase/<uuid:purchase_id>/", edit_purchase_view, name="edit_purchase"),
    path(
        "detail-purchase/<uuid:purchase_id>/",
        detail_purchase_view,
        name="detail_purchase",
    ),
    # Usage views and detail/edit views
    path("add-usage/", add_usage_view, name="add_usage_custom"),
    path("edit-usage/<uuid:usage_id>/", edit_usage_view, name="edit_usage"),
    path("detail-usage/<uuid:usage_id>/", detail_usage_view, name="detail_usage"),
]


"""
URL Configuration for Shop Manager API

This file defines all API endpoints for the secondary school inventory system.
It uses DRF DefaultRouter for all ViewSets (standard, clean, and maintainable).
Custom function-based views have been removed because the serializers now handle
all complex creation/update logic (nested items, stock updates, cost snapshots).

Available endpoints:
- /shops/, /categories/, /suppliers/, /products/, /stocks/, etc.
- /purchases/ and /sales/ (kept for backward compatibility — internally uses Usage)
- /reports/<report_type>/

All routes are protected by the permission classes defined in the ViewSets.
"""

from rest_framework.routers import DefaultRouter
from django.urls import path, include

from shop_manager import views
from shop_manager.report_views import report_view
from .custom_views import (
    add_purchase_view,
    add_usage_view,      # ← changed
    detail_purchase_view,
    detail_usage_view,   # ← changed
    edit_purchase_view,
    edit_usage_view,     # ← changed
)


# =============================================================================
# ROUTER SETUP
# =============================================================================
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

# Legacy URL names kept for frontend compatibility
router.register(r"sales", views.UsageViewSet, basename="sale")
router.register(r"saleitems", views.UsageItemViewSet, basename="saleitem")

urlpatterns = [
    # All ViewSet routes
    path("", include(router.urls)),
    # Reports endpoint
    path("reports/<str:report_type>/", report_view, name="report_view"),
    # Custom views for purchase and sale management
    path("add-purchase/", add_purchase_view, name="add_purchase_custom"),
    path("edit-purchase/<uuid:purchase_id>/", edit_purchase_view, name="edit_purchase"),
    path(
        "detail-purchase/<uuid:purchase_id>/",
        detail_purchase_view,
        name="detail_purchase",
    ),
    # Usage views and detail/edit views
    path("add-usage/", add_usage_view, name="add_usage_custom"),
    path("edit-usage/<uuid:usage_id>/", edit_usage_view, name="edit_usage"),
    path("detail-usage/<uuid:usage_id>/", detail_usage_view, name="detail_usage"),
]
