from decimal import Decimal
import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from core.models import Product, Inventory, Dealer, Order, OrderItem, OrderStatus


class CoreAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.test_prefix = uuid.uuid4().hex[:6].upper()

        # Create sample products
        self.p1 = Product.objects.create(
            sku=f"BRK-{self.test_prefix}-1",
            name="Brake Pad Front",
            category="Brakes",
            brand="Endurance",
            vehicle_fitment="Bajaj Pulsar 150",
            price=Decimal("1459.50"),
            description="High performance brake pads",
        )
        Inventory.objects.create(product=self.p1, quantity=50)

        self.p2 = Product.objects.create(
            sku=f"ENG-{self.test_prefix}-2",
            name="Engine Oil 10W40",
            category="Engine",
            brand="Motul",
            vehicle_fitment="Universal",
            price=Decimal("850.00"),
            description="Synthetic engine oil",
        )
        Inventory.objects.create(product=self.p2, quantity=100)

        # Create sample dealer
        self.dealer = Dealer.objects.create(
            dealer_code=f"DLR-{self.test_prefix}",
            name="Apex Motors",
            city="Pune",
            phone="9876543210",
            email="apex@example.com",
            gstin="27AABP5506A1Z6",
            credit_limit=Decimal("200000.00"),
        )

    def test_health_endpoint(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json(), {"status": "ok"})

    def test_pagination_defaults_limits_and_invalid(self):
        # Default page size: 20
        res = self.client.get("/api/products/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)

        # Custom page size: 5
        res_5 = self.client.get("/api/products/?page_size=5")
        self.assertEqual(res_5.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(res_5.json()["results"]), 5)

        # Invalid page (out of range) -> 404 NOT_FOUND
        res_invalid = self.client.get("/api/products/?page=99999")
        self.assertEqual(res_invalid.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_invalid.json()["error"]["code"], "NOT_FOUND")

    def test_product_list_and_filters(self):
        res = self.client.get("/api/products/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertTrue(data["count"] >= 2)

        # Filter by search
        res_search = self.client.get("/api/products/?search=Motul")
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        self.assertTrue(any(p["brand"] == "Motul" for p in res_search.json()["results"]))

        # Filter by category
        res_cat = self.client.get("/api/products/?category=Brakes")
        self.assertEqual(res_cat.status_code, status.HTTP_200_OK)
        self.assertTrue(all(p["category"] == "Brakes" for p in res_cat.json()["results"]))

        # Filter by vehicle
        res_veh = self.client.get("/api/products/?vehicle=Pulsar")
        self.assertEqual(res_veh.status_code, status.HTTP_200_OK)
        self.assertTrue(all("Pulsar" in p["vehicle_fitment"] for p in res_veh.json()["results"]))

    def test_product_create_and_duplicate(self):
        new_sku = f"CHN-{self.test_prefix}-9"
        payload = {
            "sku": new_sku,
            "name": "Drive Chain Kit",
            "category": "Drivetrain",
            "brand": "Rolon",
            "vehicle_fitment": "Yamaha R15",
            "price": "2100.50",
            "description": "Standard O-Ring chain",
        }
        res = self.client.post("/api/products/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.json()["sku"], new_sku)
        self.assertEqual(res.json()["stock"], 0)
        self.assertEqual(res.json()["price"], "2100.50")

        # Duplicate SKU -> 409 DUPLICATE
        res_dup = self.client.post("/api/products/", payload, format="json")
        self.assertEqual(res_dup.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_dup.json()["error"]["code"], "DUPLICATE")

        # Invalid price (e.g. negative or >2 decimals) -> 400 VALIDATION_ERROR
        res_bad_price = self.client.post(
            "/api/products/",
            {**payload, "sku": f"CHN-{self.test_prefix}-10", "price": "100.999"},
            format="json",
        )
        self.assertEqual(res_bad_price.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_bad_price.json()["error"]["code"], "VALIDATION_ERROR")

    def test_product_detail_and_patch(self):
        res = self.client.get(f"/api/products/{self.p1.sku}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["sku"], self.p1.sku)
        self.assertEqual(res.json()["stock"], 50)

        # 404 for non-existent
        res_404 = self.client.get("/api/products/NON-EXISTENT-SKU/")
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_404.json()["error"]["code"], "NOT_FOUND")

        # PATCH update
        res_patch = self.client.patch(
            f"/api/products/{self.p1.sku}/",
            {"price": "1599.00"},
            format="json",
        )
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.assertEqual(res_patch.json()["price"], "1599.00")

    def test_inventory_update(self):
        res = self.client.put(
            f"/api/inventory/{self.p1.sku}/",
            {"quantity": 75, "reason": "stock count adjustment"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json(), {"sku": self.p1.sku, "quantity": 75})

        # Check stock reflects on product detail
        res_prod = self.client.get(f"/api/products/{self.p1.sku}/")
        self.assertEqual(res_prod.json()["stock"], 75)

        # Unknown SKU -> 404
        res_unk = self.client.put(
            "/api/inventory/UNKNOWN-SKU-999/",
            {"quantity": 10},
            format="json",
        )
        self.assertEqual(res_unk.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_unk.json()["error"]["code"], "NOT_FOUND")

        # Invalid quantity -> 400
        res_bad = self.client.put(
            f"/api/inventory/{self.p1.sku}/",
            {"quantity": -5, "reason": "invalid"},
            format="json",
        )
        self.assertEqual(res_bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res_bad.json()["error"]["code"], "VALIDATION_ERROR")

    def test_dealer_create_list_detail(self):
        # List
        res_list = self.client.get("/api/dealers/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertIn("results", res_list.json())

        # Create
        d_code = f"DLR-{self.test_prefix}-NEW"
        res_create = self.client.post(
            "/api/dealers/",
            {"dealer_code": d_code, "name": "New Horizons Dealer", "city": "Bengaluru"},
            format="json",
        )
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        d_id = res_create.json()["id"]

        # Detail
        res_detail = self.client.get(f"/api/dealers/{d_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.json()["dealer_code"], d_code)

        # Duplicate dealer code -> 409
        res_dup = self.client.post(
            "/api/dealers/",
            {"dealer_code": d_code, "name": "Duplicate Dealer"},
            format="json",
        )
        self.assertEqual(res_dup.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_dup.json()["error"]["code"], "DUPLICATE")

        # Unknown dealer -> 404
        res_404 = self.client.get("/api/dealers/999999/")
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_404.json()["error"]["code"], "NOT_FOUND")

    def test_create_draft_order_gst_rounding_and_inventory_preservation(self):
        payload = {
            "dealer_id": self.dealer.id,
            "items": [
                {"sku": self.p1.sku, "quantity": 2},  # 1459.50 * 2 = 2919.00 -> 18% = 525.42 -> total 3444.42
                {"sku": self.p2.sku, "quantity": 1},  # 850.00 * 1 = 850.00 -> 18% = 153.00 -> total 1003.00
            ],
        }
        res = self.client.post("/api/orders/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()

        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(data["dealer_id"], self.dealer.id)
        self.assertTrue(data["order_number"].startswith("ORD-"))
        self.assertEqual(len(data["items"]), 2)

        # Calculations check:
        # Line 1: subtotal 2919.00, tax 525.42, total 3444.42
        # Line 2: subtotal 850.00, tax 153.00, total 1003.00
        # Subtotal = 3769.00, Tax = 678.42, Grand Total = 4447.42
        self.assertEqual(data["subtotal"], "3769.00")
        self.assertEqual(data["tax_total"], "678.42")
        self.assertEqual(data["grand_total"], "4447.42")

        # Verify inventory is completely UNCHANGED by draft order creation
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.stock, 50)
        self.assertEqual(self.p2.stock, 100)

        # Retrieve order detail
        res_get = self.client.get(f"/api/orders/{data['order_number']}/")
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(res_get.json()["order_number"], data["order_number"])

    def test_order_idempotency(self):
        payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": self.p1.sku, "quantity": 3}],
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": f"idem-key-{uuid.uuid4().hex}"}

        # First request
        res1 = self.client.post("/api/orders/", payload, format="json", **headers)
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        ord1 = res1.json()

        # Second request with same key and same body returns original order
        res2 = self.client.post("/api/orders/", payload, format="json", **headers)
        self.assertIn(res2.status_code, (status.HTTP_200_OK, status.HTTP_201_CREATED))
        self.assertEqual(res2.json()["order_number"], ord1["order_number"])

        # Third request with same key but different body -> 409 IDEMPOTENCY_CONFLICT
        diff_payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": self.p2.sku, "quantity": 1}],
        }
        res3 = self.client.post("/api/orders/", diff_payload, format="json", **headers)
        self.assertEqual(res3.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res3.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_order_creation_validation_errors(self):
        # Empty items list
        res = self.client.post(
            "/api/orders/",
            {"dealer_id": self.dealer.id, "items": []},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Unknown dealer
        res = self.client.post(
            "/api/orders/",
            {"dealer_id": 999999, "items": [{"sku": self.p1.sku, "quantity": 1}]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Unknown SKU
        res = self.client.post(
            "/api/orders/",
            {"dealer_id": self.dealer.id, "items": [{"sku": "NON-EXISTENT", "quantity": 1}]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Duplicate SKU in same order
        res = self.client.post(
            "/api/orders/",
            {
                "dealer_id": self.dealer.id,
                "items": [
                    {"sku": self.p1.sku, "quantity": 1},
                    {"sku": self.p1.sku, "quantity": 2},
                ],
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Invalid quantity <= 0
        res = self.client.post(
            "/api/orders/",
            {"dealer_id": self.dealer.id, "items": [{"sku": self.p1.sku, "quantity": 0}]},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

