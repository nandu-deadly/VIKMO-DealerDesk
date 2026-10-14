from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from rest_framework import serializers
from core.models import Product, Inventory, Dealer, Order, OrderItem, OrderStatus


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
        ]

    def get_price(self, obj) -> str:
        return f"{obj.price:.2f}"


class ProductCreateSerializer(serializers.ModelSerializer):
    price = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_sku(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("SKU cannot be empty.")
        return val

    def validate_price(self, value):
        try:
            val = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError("Price must be a valid number.")
        if val <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        parts = str(value).strip().split(".")
        if len(parts) == 2 and len(parts[1]) > 2:
            raise serializers.ValidationError("Price must have at most 2 decimal places.")
        return val

    def create(self, validated_data):
        product = Product.objects.create(**validated_data)
        Inventory.objects.get_or_create(product=product, defaults={"quantity": 0})
        return product


class ProductUpdateSerializer(serializers.ModelSerializer):
    price = serializers.CharField(required=False)

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_price(self, value):
        if value is None:
            return value
        try:
            val = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError("Price must be a valid number.")
        if val <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        parts = str(value).strip().split(".")
        if len(parts) == 2 and len(parts[1]) > 2:
            raise serializers.ValidationError("Price must have at most 2 decimal places.")
        return val


class DealerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
            "is_active",
        ]

    def get_credit_limit(self, obj) -> str:
        return f"{obj.credit_limit:.2f}"


class DealerCreateSerializer(serializers.ModelSerializer):
    dealer_code = serializers.CharField()
    name = serializers.CharField()
    city = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.CharField(required=False, allow_blank=True, default="")
    gstin = serializers.CharField(required=False, allow_blank=True, default="")
    credit_limit = serializers.CharField(required=False, default="0.00")
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = Dealer
        fields = [
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
            "is_active",
        ]

    def validate_dealer_code(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("dealer_code cannot be empty.")
        return val

    def validate_credit_limit(self, value):
        if not value:
            return Decimal("0.00")
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise serializers.ValidationError("credit_limit must be a valid decimal amount.")


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price = serializers.SerializerMethodField()
    line_subtotal = serializers.SerializerMethodField()
    line_tax = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        ]

    def get_unit_price(self, obj) -> str:
        return f"{obj.unit_price:.2f}"

    def get_line_subtotal(self, obj) -> str:
        return f"{obj.line_subtotal:.2f}"

    def get_line_tax(self, obj) -> str:
        return f"{obj.line_tax:.2f}"

    def get_line_total(self, obj) -> str:
        return f"{obj.line_total:.2f}"


class OrderSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(source="dealer.id")
    dealer_code = serializers.CharField(source="dealer.dealer_code", read_only=True)
    dealer_name = serializers.CharField(source="dealer.name", read_only=True)
    status_label = serializers.CharField(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    confirmed_by_username = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "dealer_code",
            "dealer_name",
            "status",
            "status_label",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
            "confirmed_by_username",
        ]

    def get_subtotal(self, obj) -> str:
        return f"{obj.subtotal:.2f}"

    def get_tax_total(self, obj) -> str:
        return f"{obj.tax_total:.2f}"

    def get_grand_total(self, obj) -> str:
        return f"{obj.grand_total:.2f}"

    def get_created_at(self, obj) -> str:
        return obj.created_at.isoformat()

    def get_updated_at(self, obj) -> str:
        return obj.updated_at.isoformat()

    def get_confirmed_by_username(self, obj) -> str:
        return obj.confirmed_by.username if obj.confirmed_by else None

