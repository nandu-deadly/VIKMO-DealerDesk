from decimal import Decimal
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from core.models import Product, Inventory, Dealer, Order, OrderItem, OrderStatus, AssistantMessage


class ModelAndSeedingTests(TestCase):
    def test_product_creation_and_sku_uniqueness(self):
        p1 = Product.objects.create(
            sku="TEST-001",
            name="Test Brake Pad",
            category="Brakes",
            brand="TestBrand",
            vehicle_fitment="TestBike",
            price=Decimal("499.50"),
            description="Test description",
        )
        self.assertEqual(p1.sku, "TEST-001")
        self.assertEqual(p1.stock, 0)
        self.assertEqual(p1.price, Decimal("499.50"))

        # Attempting duplicate SKU must fail
        with self.assertRaises(IntegrityError):
            Product.objects.create(
                sku="TEST-001",
                name="Duplicate Brake Pad",
                category="Brakes",
                brand="OtherBrand",
                vehicle_fitment="TestBike",
                price=Decimal("599.00"),
            )

    def test_inventory_relationship_and_constraint(self):
        product = Product.objects.create(
            sku="TEST-002",
            name="Test Oil Filter",
            category="Filters",
            brand="TestBrand",
            vehicle_fitment="Universal",
            price=Decimal("150.00"),
        )
        inventory = Inventory.objects.create(product=product, quantity=25)
        self.assertEqual(product.stock, 25)
        self.assertEqual(inventory.quantity, 25)

        # Negative inventory must fail CheckConstraint
        with self.assertRaises(IntegrityError):
            Inventory.objects.create(
                product=Product.objects.create(
                    sku="TEST-003",
                    name="Negative Test",
                    category="Misc",
                    brand="Test",
                    vehicle_fitment="All",
                    price=Decimal("10.00"),
                ),
                quantity=-5,
            )

    def test_dealer_creation_and_code_uniqueness(self):
        d1 = Dealer.objects.create(
            dealer_code="DLR-999",
            name="Test Dealership",
            city="Bengaluru",
            phone="9876543210",
            email="test@dealer.com",
            credit_limit=Decimal("100000.00"),
        )
        self.assertEqual(d1.dealer_code, "DLR-999")
        self.assertEqual(d1.credit_limit, Decimal("100000.00"))

        # Duplicate dealer_code must raise IntegrityError
        with self.assertRaises(IntegrityError):
            Dealer.objects.create(
                dealer_code="DLR-999",
                name="Another Dealership",
            )

    def test_order_and_order_item_relationship(self):
        dealer, _ = Dealer.objects.get_or_create(
            dealer_code="DLR-TEST-001",
            defaults={"name": "Main Dealer"},
        )
        product, _ = Product.objects.get_or_create(
            sku="BRK-TEST-001",
            defaults={
                "name": "Front Disc Pad",
                "category": "Brakes",
                "brand": "Brembo",
                "vehicle_fitment": "KTM 390",
                "price": Decimal("1200.00"),
            },
        )
        order = Order.objects.create(
            order_number="ORD-20261010-0001",
            dealer=dealer,
            status=OrderStatus.DRAFT,
            subtotal=Decimal("2400.00"),
            tax_total=Decimal("432.00"),
            grand_total=Decimal("2832.00"),
        )
        item = OrderItem.objects.create(
            order=order,
            product=product,
            sku=product.sku,
            name=product.name,
            quantity=2,
            unit_price=product.price,
            line_subtotal=Decimal("2400.00"),
            line_tax=Decimal("432.00"),
            line_total=Decimal("2832.00"),
        )
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, Decimal("1200.00"))
        self.assertEqual(item.line_total, Decimal("2832.00"))

        # Duplicate product in same order must fail constraint
        with self.assertRaises(IntegrityError):
            OrderItem.objects.create(
                order=order,
                product=product,
                sku=product.sku,
                name=product.name,
                quantity=1,
                unit_price=product.price,
                line_subtotal=Decimal("1200.00"),
                line_tax=Decimal("216.00"),
                line_total=Decimal("1416.00"),
            )

    def test_assistant_message_model(self):
        msg = AssistantMessage.objects.create(
            session_id="session-test-1",
            role="user",
            content="Looking for Pulsar brake pads",
            metadata={"source": "test"},
        )
        self.assertEqual(msg.session_id, "session-test-1")
        self.assertEqual(msg.role, "user")
        self.assertIn("Pulsar", str(msg))

    def test_seeding_idempotency_and_counts(self):
        # Clean up any records before verifying seed data
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Inventory.objects.all().delete()
        Product.objects.all().delete()
        Dealer.objects.all().delete()

        # First seed
        call_command("seed_data")
        self.assertEqual(Product.objects.count(), 600)
        self.assertEqual(Dealer.objects.count(), 25)
        self.assertEqual(Inventory.objects.count(), 600)

        # Modify one inventory quantity to simulate live business operation
        sample_inv = Inventory.objects.first()
        original_qty = sample_inv.quantity
        sample_inv.quantity = original_qty + 10
        sample_inv.save()

        # Second seed (idempotency check)
        call_command("seed_data")
        self.assertEqual(Product.objects.count(), 600)
        self.assertEqual(Dealer.objects.count(), 25)
        self.assertEqual(Inventory.objects.count(), 600)

        # Verify live stock was preserved across re-seed
        sample_inv.refresh_from_db()
        self.assertEqual(sample_inv.quantity, original_qty + 10)

