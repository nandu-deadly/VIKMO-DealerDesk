from decimal import Decimal
from django.core.management import call_command
from django.test import TestCase, Client
from core.models import Product, Dealer, Inventory


class FrontendDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.product = Product.objects.create(
            sku="DASH-BRK-01",
            name="Dashboard Ceramic Brake Pad",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="Pulsar 220",
            price=Decimal("499.00"),
            description="High-friction brake pads",
        )
        self.inventory = Inventory.objects.create(product=self.product, quantity=50)
        self.dealer = Dealer.objects.create(
            dealer_code="DLR-DASH-01",
            name="Apex Motors",
            city="Bengaluru",
            phone="9876543210",
        )

    def test_dashboard_renders_successfully(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check core UI sections
        self.assertIn("VIKMO DealerDesk", content)
        self.assertIn("Quick Operations Overview", content)
        self.assertIn("Catalogue & Live Inventory", content)
        self.assertIn("Create Draft Order", content)
        self.assertIn("Dealer Parts Assistant (GenAI)", content)
        self.assertIn("Inventory Reorder Recommendations", content)
        self.assertIn("Supplier Catalogue Synchronization", content)

        # Check UI components
        self.assertIn("chat-input", content)
        self.assertIn("chat-send-btn", content)
        self.assertIn("sync-trigger-btn", content)
        self.assertIn("prod-search", content)
        self.assertIn("order-sku", content)

    def test_dashboard_product_pagination_controls_rendered(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check pagination and filter controls
        self.assertIn("prod-count-summary", content)
        self.assertIn("products-pagination-container", content)
        self.assertIn("prod-pagination-nav", content)
        self.assertIn("prod-pagination-summary", content)
        self.assertIn("prod-jump-page", content)
        self.assertIn("prod-page-size", content)
        self.assertIn("btn-load-more", content)
        self.assertIn("prod-vehicle", content)
        self.assertIn("btn-search-products", content)


class ProductCataloguePaginationAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Clean any leftovers in test database and seed exact 600 catalogue products
        from core.models import OrderItem, Order
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        Inventory.objects.all().delete()
        Product.objects.all().delete()
        call_command("seed_data")

    def setUp(self):
        self.client = Client()

    def test_full_catalogue_pagination_traversal_all_600_products(self):
        """Verifies that following pagination links traverses all pages and yields exactly 600 unique products."""
        url = "/api/products/?page_size=20"
        seen_skus = set()
        total_pages = 0
        expected_fields = {"sku", "name", "category", "brand", "vehicle_fitment", "price", "stock", "description"}

        while url:
            total_pages += 1
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            data = res.json()

            self.assertEqual(data["count"], 600)
            results = data.get("results", [])
            for item in results:
                sku = item["sku"]
                self.assertNotIn(sku, seen_skus, f"Duplicate SKU {sku} encountered across pages.")
                seen_skus.add(sku)
                for f in expected_fields:
                    self.assertIn(f, item, f"Field '{f}' missing from product {sku}")

            url = data.get("next")

        self.assertEqual(total_pages, 30)
        self.assertEqual(len(seen_skus), 600)

    def test_page_size_100_yields_6_pages_of_all_600_products(self):
        """Verifies that setting page_size=100 allows fetching 100 products per page across 6 pages."""
        url = "/api/products/?page_size=100"
        seen_skus = set()
        pages = 0

        while url:
            pages += 1
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["count"], 600)
            for item in data.get("results", []):
                seen_skus.add(item["sku"])
            url = data.get("next")

        self.assertEqual(pages, 6)
        self.assertEqual(len(seen_skus), 600)

    def test_search_and_category_filtering_across_pages(self):
        """Verifies filtering by category and search term correctly filters results."""
        # Category filter: Brakes
        res = self.client.get("/api/products/?category=Brakes&page_size=100")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreater(data["count"], 0)
        for item in data["results"]:
            self.assertEqual(item["category"].lower(), "brakes")

        # Search filter: Pulsar
        res_search = self.client.get("/api/products/?search=Pulsar&page_size=100")
        self.assertEqual(res_search.status_code, 200)
        search_data = res_search.json()
        self.assertGreater(search_data["count"], 0)
        for item in search_data["results"]:
            matches = (
                "pulsar" in item["sku"].lower()
                or "pulsar" in item["name"].lower()
                or "pulsar" in item["brand"].lower()
                or "pulsar" in item["vehicle_fitment"].lower()
            )
            self.assertTrue(matches, f"Product {item['sku']} did not match search term 'Pulsar'")
