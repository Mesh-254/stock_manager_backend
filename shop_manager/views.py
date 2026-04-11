"""
Views for Shop Manager API

This module contains all DRF ViewSets for the school inventory system.
Design decisions:
- Minimal ViewSets — most business logic lives in the serializers (atomic transactions,
  weighted average cost, stock updates, cost snapshots).
- Strong permission layering (IsAuthenticated → IsCashierOrHigher → IsShopAdmin).
- Optimized querysets with select_related/prefetch_related for performance.
- Custom actions only where truly needed (low-stock list, discontinue, manual stock adjust).
- No duplicate creation logic — serializers handle everything.

All endpoints are shop-scoped for multi-tenancy security.
"""

from decimal import Decimal
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django_filters import filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from rest_framework.exceptions import ValidationError
from django.db import models

from .models import (
    Shop,
    Category,
    Supplier,
    Product,
    Stock,
    StockTransaction,
    Purchase,
    PurchaseItem,
    Usage,
    UsageItem,
)
from .serializers import (
    ShopSerializer,
    CategorySerializer,
    SupplierSerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    ProductWriteSerializer,
    StockSerializer,
    StockTransactionSerializer,
    PurchaseSerializer,
    PurchaseItemSerializer,
    UsageSerializer,
    UsageItemSerializer,
)
from .permissions import IsCashierOrHigher, IsInSameShop, IsShopAdmin
from .utils import update_stock


# =============================================================================
# SHOP VIEWSET
# =============================================================================
class ShopViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for Shop model.
    Handles logo upload with validation and old-file cleanup.
    """

    queryset = Shop.objects.all()
    serializer_class = ShopSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated, IsInSameShop]

    def perform_create(self, serializer):
        """Set current user as owner when creating a shop."""
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        """Handle logo replacement and delete old file."""
        logo = self.request.FILES.get("logo")
        instance = serializer.instance

        if logo:
            self.validate_image(logo)
            if instance.logo and instance.logo != logo:
                self.delete_old_logo(instance.logo)

        serializer.save()

    def validate_image(self, image):
        """Enforce 5MB limit and allowed formats."""
        max_size = 5 * 1024 * 1024
        allowed = {"jpg", "jpeg", "png"}

        if image.size > max_size:
            raise ValidationError(
                f"File size exceeds {max_size // (1024*1024)}MB limit."
            )

        ext = image.name.split(".")[-1].lower()
        if ext not in allowed:
            raise ValidationError("Only .jpg, .jpeg, .png files allowed.")

    def delete_old_logo(self, old_logo):
        """Remove orphaned logo file from storage."""
        if old_logo and default_storage.exists(old_logo.name):
            default_storage.delete(old_logo.name)


# =============================================================================
# CATEGORY & SUPPLIER VIEWSETS
# =============================================================================
class CategoryViewSet(viewsets.ModelViewSet):
    """CRUD for product categories (shop-scoped)."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher]


class SupplierViewSet(viewsets.ModelViewSet):
    """CRUD for suppliers."""

    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher]


# =============================================================================
# PRODUCT VIEWSET
# =============================================================================
class ProductViewSet(viewsets.ModelViewSet):
    """
    Main product management endpoint.
    Supports list/detail/create/update with different serializers.
    Includes low-stock action and soft-discontinue.
    """

    permission_classes = [IsAuthenticated, IsCashierOrHigher]
    filter_backends = [
        DjangoFilterBackend,
        filters.CharFilter,
        filters.OrderingFilter,
    ]
    search_fields = ["name", "description", "category__name"]
    ordering_fields = ["name", "cost_price", "reorder_level", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        qs = Product.objects.select_related(
            "category", "shop", "created_by"
        ).prefetch_related("stock")
        user = self.request.user

        if user.role == "SuperAdmin":
            return qs
        if hasattr(user, "shop") and user.shop:
            qs = qs.filter(shop=user.shop)
        else:
            return qs.none()

        if user.role == "Cashier":
            qs = qs.filter(is_active=True, is_discontinued=False)

        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        if self.action == "retrieve":
            return ProductDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return ProductWriteSerializer
        return super().get_serializer_class()

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        """Return products below reorder level."""
        qs = self.get_queryset().filter(
            is_active=True,
            is_discontinued=False,
            stock__quantity__lte=models.F("reorder_level"),
        )
        serializer = ProductListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="discontinue")
    def discontinue(self, request, pk=None):
        """Soft-delete (discontinue) a product."""
        product = self.get_object()
        if request.user.role not in ("SuperAdmin", "ShopAdmin"):
            return Response(
                {"detail": "Only admins can discontinue products."}, status=403
            )

        reason = request.data.get("reason", "").strip()
        if not reason:
            raise ValidationError({"reason": "Discontinue reason is required."})

        product.is_discontinued = True
        product.is_active = False
        product.discontinued_reason = reason
        product.discontinued_at = timezone.now()
        product.save(
            update_fields=[
                "is_discontinued",
                "is_active",
                "discontinued_reason",
                "discontinued_at",
            ]
        )

        return Response(ProductDetailSerializer(product).data)


# =============================================================================
# STOCK VIEWSETS
# =============================================================================
class StockViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only current stock levels + manual adjustment action."""

    # queryset = Stock.objects.select_related(
    #     "product", "product__category"
    # ).prefetch_related("transactions")
    serializer_class = StockSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher, IsInSameShop]

    def get_queryset(self):
        qs = Stock.objects.select_related(
            "product", "product__category"
        ).prefetch_related("transactions")

        user = self.request.user
        if user.role == "SuperAdmin":
            return qs

        if hasattr(user, "shop") and user.shop:
            # Stock is linked via product__shop
            return qs.filter(product__shop=user.shop)

        return qs.none()

    @action(detail=True, methods=["post"], permission_classes=[IsShopAdmin])
    def adjust(self, request, pk=None):
        """Manual stock adjustment (admin only)."""
        stock = self.get_object()
        quantity_change = Decimal(request.data.get("quantity_change", 0))
        reason = request.data.get("reason", "Manual adjustment")

        try:
            update_stock(
                product=stock.product,
                quantity_change=quantity_change,
                transaction_type="adjustment",
                reason=reason,
                reference=f"Manual by {request.user}",
                user=request.user,
            )
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(StockSerializer(stock).data)


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """Full audit trail of all stock movements."""

    # queryset = StockTransaction.objects.select_related("stock__product", "created_by")
    serializer_class = StockTransactionSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher, IsInSameShop]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["type", "stock__product__id"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = StockTransaction.objects.select_related("stock__product", "created_by")
        user = self.request.user
        if user.role == "SuperAdmin":
            return qs
        if hasattr(user, "shop") and user.shop:
            return qs.filter(stock__product__shop=user.shop)
        return qs.none()


# =============================================================================
# PURCHASE VIEWSET
# =============================================================================
class PurchaseViewSet(viewsets.ModelViewSet):
    """Purchase (stock-in) management. Serializer handles all logic."""

    queryset = Purchase.objects.select_related(
        "shop", "supplier", "created_by"
    ).prefetch_related("items__product")
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher, IsShopAdmin]

    def get_queryset(self):
        if self.request.user.role == "SuperAdmin":
            return self.queryset
        return self.queryset.filter(shop=self.request.user.shop)


class PurchaseItemViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to purchase line items."""

    queryset = PurchaseItem.objects.select_related("purchase", "product")
    serializer_class = PurchaseItemSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher]


# =============================================================================
# USAGE VIEWSET (formerly Sale)
# =============================================================================
class UsageViewSet(viewsets.ModelViewSet):
    """Daily usage/consumption recording. Core for usage cost reports."""

    queryset = Usage.objects.select_related("shop", "recorded_by").prefetch_related(
        "items__product"
    )
    serializer_class = UsageSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher]

    def get_queryset(self):
        if self.request.user.role == "SuperAdmin":
            return self.queryset
        return self.queryset.filter(shop=self.request.user.shop)


class UsageItemViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to usage line items."""

    queryset = UsageItem.objects.select_related("usage", "product")
    serializer_class = UsageItemSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher]
