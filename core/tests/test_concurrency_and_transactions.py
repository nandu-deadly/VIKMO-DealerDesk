import threading
from decimal import Decimal
from django.test import TransactionTestCase
from django.db import connection

from core.models import Product, Inventory, Dealer, Order, OrderStatus
from core.order_service import OrderService
from core.exceptions import InsufficientStockException


class ConcurrencyAndTransactionTests(TransactionTestCase):
    """PostgreSQL-backed concurrency and transaction isolation tests.
    
    Uses TransactionTestCase so real database transactions and row-level locks
    (SELECT ... FOR UPDATE) are committed and tested across independent worker threads.
    """

    def setUp(self):
        super().setUp()
        self.dealer = Dealer.objects.create(
            dealer_code="CONC-DLR-01",
            name="Concurrency Test Dealer",
            credit_limit=Decimal("500000.00"),
        )
        self.product = Product.objects.create(
            sku="CONC-PRD-01",
            name="High Performance Brake Pad",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="KTM Duke 390",
            price=Decimal("1200.00"),
        )
        # Starting inventory: exactly 5 units
        self.inventory = Inventory.objects.create(
            product=self.product,
            quantity=5,
        )

    def tearDown(self):
        # Clean up database connections
        connection.close()
        super().tearDown()

    def test_concurrent_order_confirmation_prevents_overselling(self):
        """Proves that PostgreSQL row-level locking (select_for_update) prevents overselling
        when two concurrent transactions attempt to confirm orders requiring more total stock
        than available.
        """
        # Order 1 requires 4 units (5 available -> ok if first)
        order1, _ = OrderService.create_order(
            dealer_id=self.dealer.id,
            items_data=[{"sku": self.product.sku, "quantity": 4}],
        )
        # Order 2 requires 3 units (5 available -> ok if first, but 4 + 3 = 7 > 5)
        order2, _ = OrderService.create_order(
            dealer_id=self.dealer.id,
            items_data=[{"sku": self.product.sku, "quantity": 3}],
        )

        successful_orders = []
        captured_exceptions = []
        barrier = threading.Barrier(2)

        def worker(order_number):
            # Close existing thread-local connection so a new independent connection to PostgreSQL is opened
            connection.close()
            try:
                barrier.wait(timeout=5)
                confirmed = OrderService.confirm_order(order_number)
                successful_orders.append(confirmed.order_number)
            except Exception as exc:
                captured_exceptions.append(exc)
            finally:
                connection.close()

        t1 = threading.Thread(target=worker, args=(order1.order_number,))
        t2 = threading.Thread(target=worker, args=(order2.order_number,))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Reopen main test connection
        connection.connect()

        # Exactly ONE order should have succeeded, and ONE failed due to insufficient stock
        self.assertEqual(
            len(successful_orders),
            1,
            f"Expected exactly 1 successful confirmation, got {len(successful_orders)}: {successful_orders}",
        )
        self.assertEqual(
            len(captured_exceptions),
            1,
            f"Expected exactly 1 exception, got {len(captured_exceptions)}: {captured_exceptions}",
        )
        self.assertIsInstance(
            captured_exceptions[0],
            InsufficientStockException,
            f"Expected InsufficientStockException, got {type(captured_exceptions[0])}",
        )

        # Verify PostgreSQL database state: inventory was correctly decremented and NEVER went negative
        self.inventory.refresh_from_db()
        # If Order 1 (qty 4) won: remaining is 5 - 4 = 1
        # If Order 2 (qty 3) won: remaining is 5 - 3 = 2
        self.assertIn(self.inventory.quantity, (1, 2))
        self.assertGreaterEqual(self.inventory.quantity, 0)

        # Verify orders state in database
        ord1 = Order.objects.get(order_number=order1.order_number)
        ord2 = Order.objects.get(order_number=order2.order_number)
        statuses = {ord1.status, ord2.status}
        self.assertEqual(statuses, {OrderStatus.CONFIRMED, OrderStatus.DRAFT})

    def test_concurrent_order_creation_allocates_unique_order_numbers(self):
        """Proves that multiple concurrent order creations across separate PostgreSQL connections
        generate collision-free, sequential ORD-YYYYMMDD-NNNN order numbers.
        """
        thread_count = 5
        created_orders = []
        errors = []
        barrier = threading.Barrier(thread_count)

        def create_worker():
            connection.close()
            try:
                barrier.wait(timeout=5)
                ord_obj, _ = OrderService.create_order(
                    dealer_id=self.dealer.id,
                    items_data=[{"sku": self.product.sku, "quantity": 1}],
                )
                created_orders.append(ord_obj.order_number)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=create_worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        connection.connect()
        self.assertEqual(len(errors), 0, f"Concurrent order creation generated errors: {errors}")
        self.assertEqual(len(created_orders), thread_count)
        # All order numbers must be strictly unique
        self.assertEqual(len(set(created_orders)), thread_count)

    def test_concurrent_idempotency_key_deduplication(self):
        """Proves that multiple concurrent POST requests sharing the same Idempotency-Key
        safely deduplicate to the exact same order without duplicates or races.
        """
        thread_count = 5
        key = "test-concurrent-idem-suite-12345"
        created_orders = []
        errors = []
        barrier = threading.Barrier(thread_count)

        def worker(wid):
            connection.close()
            try:
                barrier.wait(timeout=5)
                ord_obj, is_new = OrderService.create_order(
                    dealer_id=self.dealer.id,
                    items_data=[{"sku": self.product.sku, "quantity": 1}],
                    idempotency_key=key,
                    raw_body={"dealer_id": self.dealer.id, "items": [{"sku": self.product.sku, "quantity": 1}]},
                )
                created_orders.append((ord_obj.order_number, is_new))
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        connection.connect()
        self.assertEqual(len(errors), 0, f"Errors in concurrent idempotency: {errors}")
        self.assertEqual(len(created_orders), thread_count)
        unique_order_numbers = set(item[0] for item in created_orders)
        self.assertEqual(len(unique_order_numbers), 1)

    def test_exact_gst_round_half_up_boundary_cases(self):
        """Proves that per-line GST calculations use exact Decimal arithmetic and
        ROUND_HALF_UP to the paisa (0.005 -> 0.01).
        """
        p_boundary = Product.objects.create(
            sku="BND-HALF-UP-01",
            name="Boundary Precision Part",
            category="Precision",
            brand="Bosch",
            vehicle_fitment="Universal",
            price=Decimal("0.25"),  # 0.25 * 1 * 0.18 = 0.0450 -> 0.05
        )
        Inventory.objects.create(product=p_boundary, quantity=50)

        order, _ = OrderService.create_order(
            dealer_id=self.dealer.id,
            items_data=[{"sku": p_boundary.sku, "quantity": 1}],
        )

        item = order.items.first()
        self.assertEqual(item.line_subtotal, Decimal("0.25"))
        self.assertEqual(item.line_tax, Decimal("0.05"))
        self.assertEqual(item.line_total, Decimal("0.30"))
        self.assertEqual(order.subtotal, Decimal("0.25"))
        self.assertEqual(order.tax_total, Decimal("0.05"))
        self.assertEqual(order.grand_total, Decimal("0.30"))

