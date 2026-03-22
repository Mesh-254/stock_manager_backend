from rest_framework.routers import DefaultRouter
from django.urls import path, include
from shop_manager import views
from shop_manager.report_views import report_view
from .custom_views import add_purchase_view, add_sale_view, detail_purchase_view, detail_sale_view, edit_purchase_view, edit_sale_view


# Create a router and register our viewset with it.
router = DefaultRouter()

router.register(
    r"subscriptionplans", views.SubscriptionPlanViewSet, basename="subscriptionplan"
)
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
router.register(r"sales", views.SaleViewSet, basename="sale")
router.register(r"saleitems", views.SaleItemViewSet, basename="saleitem")


urlpatterns = [
    path("", include(router.urls)),
    path("reports/<str:report_type>/", report_view, name="report_view"),

    # Custom views for purchase and sale management
    path('add-purchase/', add_purchase_view, name='add_purchase_custom'),
    path('edit-purchase/<uuid:purchase_id>/', edit_purchase_view, name='edit_purchase'),
    path('detail-purchase/<uuid:purchase_id>/', detail_purchase_view, name='detail_purchase'),

    # Sale views and detail/edit views
    path('add-sale/', add_sale_view, name='add_sale_custom'),
    path('edit-sale/<uuid:sale_id>/', edit_sale_view, name='edit_sale'),
    path('detail-sale/<uuid:sale_id>/', detail_sale_view, name='detail_sale'),
]
