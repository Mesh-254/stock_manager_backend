from decimal import Decimal
from time import timezone
from warnings import filters
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from .models import *
from .serializers import *
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.db import transaction
from .signals import recalculate_average_cost, recalculate_purchase_total
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication
from .permissions import IsCashierOrHigher, IsInSameShop, IsShopAdmin
from rest_framework.decorators import action
from .utils import update_stock


# ==================== SubscriptionPlan ViewSet ====================


class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing subscription plan instances.
    """

    queryset = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer


# ==================== Shop ViewSet ====================


class ShopViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing Shop instances.
    It supports GET, POST, PUT, PATCH, and DELETE operations.
    """

    queryset = Shop.objects.all()
    serializer_class = ShopSerializer
    # Enable file upload handling
    parser_classes = (MultiPartParser, FormParser)

    def perform_create(self, serializer):
        """
        Custom method to handle the creation of a shop.
        Validates the image and assigns the owner as the currently authenticated user.
        """
        logo = self.request.FILES.get("logo", None)

        # Image validation: size and format checks
        if logo:
            self.validate_image(logo)

        # Save the shop instance
        # Set the owner as the current authenticated user
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        """
        Custom method to handle the update of a shop, including image deletion and validation.
        """
        # Handle logo (image) field
        logo = self.request.FILES.get("logo", None)

        # Image validation: size and format checks
        if logo:
            self.validate_image(logo)

        # Handle logo update (deleting the old logo if there's a new one)
        instance = serializer.instance
        if logo:
            old_logo = instance.logo
            # If the old logo exists and is different from the new one, delete it
            if old_logo and old_logo != logo:
                self.delete_old_logo(old_logo)

        # Save the updated shop instance
        serializer.save()

    def validate_image(self, image):
        """
        Validates the uploaded image to check its file size and type.
        """
        max_size = 5 * 1024 * 1024  # 5MB file size limit
        allowed_extensions = ["jpg", "jpeg", "png"]

        # Check the image file size
        if image.size > max_size:
            raise ValidationError(
                f"File size exceeds the {max_size // (1024 * 1024)}MB limit."
            )

        # Check the image file extension
        extension = image.name.split(".")[-1].lower()
        if extension not in allowed_extensions:
            raise ValidationError(
                "Invalid file type. Only .jpg, .jpeg, and .png files are allowed."
            )

    def delete_old_logo(self, old_logo):
        """
        Deletes the old logo file from storage to prevent orphaned files.
        """
        if old_logo:
            try:
                # Check if the file exists and delete it
                if default_storage.exists(old_logo.name):
                    default_storage.delete(old_logo.name)
            except Exception as e:
                raise DjangoValidationError(f"Error deleting old logo: {str(e)}")


# ==================== Category ViewSet ====================


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


# ==================== Supplier ViewSet ====================


class SupplierViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing Supplier instances.
    """

    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer


# ==================== Product ViewSet ====================


class ProductViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing car parts / inventory products.

    Permissions matrix:
    ┌─────────────┬─────────┬────────────┬──────────┐
    │ Role        │ List    │ Retrieve   │ Create/Update/Delete │
    ├─────────────┼─────────┼────────────┼──────────────────────┤
    │ SuperAdmin  │ Yes     │ Yes        │ Yes (all shops)      │
    │ ShopAdmin   │ Yes     │ Yes        │ Yes (own shop)       │
    │ Cashier     │ Yes     │ Yes        │ No                   │
    └─────────────┴─────────┴────────────┴──────────────────────┘

    Features:
    • Search:name, category, brand, compatible vehicles
    • Filter: category, brand, supplier, stock level, discontinued
    • Low-stock list
    • Soft delete (discontinue with reason)
    • Basic history endpoint (extendable)
    """

    queryset = Product.objects.select_related(
        "category", "brand", "supplier", "shop", "created_by"
    ).prefetch_related("stock")

    permission_classes = [IsAuthenticated, IsCashierOrHigher]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = [
        "name",
        "description",
        "compatible_vehicles",
        "brand__name",
        "category__name",
        "supplier__name",
    ]

    ordering_fields = [
        "name",
        "selling_price",
        "cost_price",
        "reorder_level",
        "created_at",
        # if you expose stock in ordering, use annotation or property
    ]

    ordering = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        if self.action == "retrieve":
            return ProductDetailSerializer
        if self.action in ["create", "update", "partial_update"]:
            return ProductWriteSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # SuperAdmin sees everything
        if user.role == "SuperAdmin":
            return qs

        # Filter by shop
        if hasattr(user, "shop") and user.shop:
            qs = qs.filter(shop=user.shop)
        else:
            return qs.none()

        # Cashiers usually shouldn't see discontinued items
        if user.role == "Cashier":
            qs = qs.filter(is_active=True, is_discontinued=False)

        return qs

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        """List products that are at or below reorder level"""
        qs = (
            self.get_queryset()
            .filter(is_active=True, is_discontinued=False)
            .filter(stock__quantity__lte=models.F("reorder_level"))
        )
        serializer = ProductListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="discontinue")
    def discontinue(self, request, pk=None):
        """Mark product as discontinued (soft delete)"""
        product = self.get_object()

        if request.user.role not in ("SuperAdmin", "ShopAdmin"):
            return Response(
                {"detail": "Only admins can discontinue products."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reason = request.data.get("reason", "").strip()
        if not reason:
            raise serializers.ValidationError(
                {"reason": "Discontinue reason is required."}
            )

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

    def perform_create(self, serializer):
        # Automatically set shop and creator
        serializer.save(
            shop=self.request.user.shop if hasattr(self.request.user, "shop") else None,
            created_by=self.request.user,
        )

    def perform_destroy(self, instance):
        # Prevent hard delete — force usage of discontinue action
        raise serializers.ValidationError(
            "Products cannot be hard-deleted. Use the /discontinue/ action instead."
        )


# ==================== Category ViewSet ====================


class StockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stock.objects.select_related(
        "product", "product__category"
    ).prefetch_related("transactions")
    serializer_class = StockSerializer
    permission_classes = [IsCashierOrHigher & IsInSameShop]
    permission_classes = [IsAuthenticated, IsCashierOrHigher, IsInSameShop]

    @action(detail=True, methods=["post"], permission_classes=[IsShopAdmin])
    def adjust(self, request, pk=None):
        stock = self.get_object()
        quantity_change = request.data["quantity_change"]
        reason = request.data.get("reason", "")

        try:
            update_stock(
                product=stock.product,
                quantity_change=quantity_change,
                transaction_type="adjustment",
                reason=reason or "Manual adjustment",
                reference=f"Manual by {request.user}",
                user=request.user,
            )
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(StockSerializer(stock).data)


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only history of all stock movements for reporting.
    """

    queryset = StockTransaction.objects.select_related("stock__product", "created_by")
    serializer_class = StockTransactionSerializer
    permission_classes = [IsCashierOrHigher, IsInSameShop]

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["type", "stock__product"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]


# ==================== Purchase ViewSet ====================


class PurchaseViewSet(viewsets.ModelViewSet):
    """
    A ViewSet to manage Purchases.

    What it does:
    - Allows creating a new Purchase with multiple items
    - Allows updating a Purchase (only limited fields)
    - Disables deleting purchases (optional, see commented code)

    Query optimization:
    - When listing purchases, also pre-load related shop, supplier, creator, and items with their products for speed.
    """

    queryset = (
        Purchase.objects.select_related("shop", "supplier", "created_by")
        .prefetch_related(
            "items__product"  # Load all related purchase items and their products
        )
        .select_related(
            "shop",  # Load the shop in a single query
            "supplier",  # Load the supplier in a single query
            "created_by",  # Load the user who created the purchase
        )
    )
    serializer_class = PurchaseSerializer
    authentication_classes = [
        SessionAuthentication
    ]  # Critical for session auth from template
    permission_classes = [
        IsAuthenticated,
        IsCashierOrHigher,
        IsShopAdmin,
    ]  # Adjust if cashiers can purchase

    def get_queryset(self):
        if self.request.user.role == "SuperAdmin":
            return self.queryset.all()
        return self.queryset.filter(shop=self.request.user.shop)

    def create(self, request, *args, **kwargs):
        """
        Handle creating a new Purchase record along with its Purchase Items.

        Steps:
        1. Validate the incoming data.
        2. Extract purchase items from the data.
        3. Save the Purchase itself.
        4. Save each Purchase Item.
        5. Update the stock levels for each product.
        6. Recalculate the total cost of the Purchase.

        Notes:
        - This happens inside a database transaction. If any step fails, nothing is saved.
        """

        # Step 1: Validate incoming request data using the serializer
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Step 2: Remove the 'items' from validated data, to handle separately
        items_data = serializer.validated_data.pop("items")

        # Auto-set created_by and shop (existing code)
        serializer.validated_data["created_by"] = request.user
        if request.user.role == "ShopAdmin":
            serializer.validated_data["shop"] = request.user.shop

        # Step 3: Start a database transaction
        with transaction.atomic():
            # Create the Purchase record (excluding the purchase items for now)
            purchase = Purchase.objects.create(
                **serializer.validated_data, total_amount=Decimal(0.00)
            )

            # Step 4: Prepare to create multiple PurchaseItem records
            purchase_items = []  # List to hold PurchaseItem objects
            stock_updates = []  # List to hold Stock updates for each product

            # Step 5: Loop through each item to create purchase items and update stock
            for item_data in items_data:
                # Get the actual Product instance
                product = Product.objects.get(pk=item_data["product"].pk)

                # Get the unit cost price for the item (use existing product price if not provided)
                unit_cost_price = Decimal(
                    item_data.get("unit_cost_price", product.cost_price)
                )

                # Create a PurchaseItem object (but don't save yet)
                purchase_items.append(
                    PurchaseItem(
                        purchase=purchase,
                        product=product,
                        quantity=item_data["quantity"],
                        unit_cost_price=unit_cost_price,
                        brand=item_data.get("brand"),
                    )
                )

                # Use update_stock instead of manual increment
                update_stock(
                    product=product,
                    quantity_change=item_data["quantity"],
                    transaction_type="purchase",
                    reason=f"New purchase item added (Purchase #{purchase.id})",
                    reference=str(purchase.id),
                    user=request.user,
                )

            # Step 6: Save all Purchase Items at once (bulk create = very fast)
            PurchaseItem.objects.bulk_create(purchase_items)

            # Recalculate weighted average cost for all affected products (bulk_create bypasses signals)
            affected_products = {item.product for item in purchase_items if item.product}
            for product in affected_products:
                recalculate_average_cost(product)

            # Step 7: Save all updated Stock records at once (bulk update = very fast)
            Stock.objects.bulk_update(stock_updates, ["quantity"])

            # Step 8: Update the total cost of the purchase
            recalculate_purchase_total(purchase)

            # Step 9: Serialize the newly created purchase and return it
            output_serializer = self.get_serializer(purchase)
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """
        Allow updating only specific fields of an existing Purchase.

        Allowed fields for update:
        - payment_status (e.g., Paid, Pending, Overdue)
        - payment_method (e.g., Cash, Card, Bank Transfer)
        - supplier (change supplier if needed)

        If someone tries to update any other field (like purchase items, date, etc), they will get an error.
        """

        # Step 1: Get the existing Purchase instance
        instance = self.get_object()

        # Step 2: Define which fields are allowed to be updated
        allowed_fields = {"payment_status", "payment_method", "supplier"}
        incoming_keys = set(request.data.keys())

        # Step 3: Check if the user is trying to update anything else (not allowed)
        if not incoming_keys.issubset(allowed_fields):
            return Response(
                {
                    "detail": "Only payment_status, payment_method, and supplier can be updated."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Step 4: Validate and save the updated data
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Step 5: Return the updated Purchase
        return Response(serializer.data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()  # Signals now handle stock reversal
        return Response(status=status.HTTP_204_NO_CONTENT)


# ==================== PurchaseItems ViewSet ====================
class PurchaseItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseItem.objects.select_related("purchase", "product")
    serializer_class = PurchaseItemSerializer
    permission_classes = [IsShopAdmin, IsCashierOrHigher]




# ==================== SaleViewSet ====================


class SaleViewSet(viewsets.ModelViewSet):
    queryset = Sale.objects.all()
    serializer_class = SaleSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, IsCashierOrHigher]

    def create(self, request, *args, **kwargs):
        """
        Create a Sale and its associated SaleItems.
        """
        data = request.data
        serializer = self.get_serializer(data=data)

        # Validate and create the sale and its items
        if serializer.is_valid():
            sale = serializer.save()
            return Response(
                self.get_serializer(sale).data, status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SaleItemViewSet(viewsets.ModelViewSet):
    queryset = SaleItem.objects.select_related("sale", "product")
    serializer_class = SaleItemSerializer
    permission_classes = [IsAuthenticated, IsCashierOrHigher]

    def perform_create(self, serializer):
        item = serializer.save()
        try:
            update_stock(
                product=item.product,
                quantity_change=-item.quantity,
                transaction_type="sale",
                reason=f"Sale {item.sale.id}",
                reference=str(item.sale.id),
                user=self.request.user,
            )
        except ValidationError as e:
            raise ValidationError({"detail": str(e)})

    def perform_update(self, serializer):
        old_item = self.get_object()
        old_qty = old_item.quantity
        item = serializer.save()
        diff = old_qty - item.quantity  # Positive = returning to stock

        if diff != 0:
            update_stock(
                product=item.product,
                quantity_change=diff,
                transaction_type="sale",
                reason=f"Sale update {item.sale.id}",
                reference=str(item.sale.id),
                user=self.request.user,
            )

    def perform_destroy(self, instance):
        update_stock(
            product=instance.product,
            quantity_change=instance.quantity,  # Return to stock
            transaction_type="sale",
            reason=f"Sale item cancelled {instance.sale.id}",
            reference=str(instance.sale.id),
            user=self.request.user,
        )
        instance.delete()
