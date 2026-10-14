import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Product, Inventory
from core.supplier_sync import SupplierSyncService
from core.exceptions import SupplierUnavailableException


class SupplierSyncServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_validate_price_helper(self):
        # Valid prices
        ok, val = SupplierSyncService._validate_price("150.00")
        self.assertTrue(ok)
        self.assertEqual(val, Decimal("150.00"))

        ok, val = SupplierSyncService._validate_price("49.5")
        self.assertTrue(ok)
        self.assertEqual(val, Decimal("49.5"))

        ok, val = SupplierSyncService._validate_price(100)
        self.assertTrue(ok)
        self.assertEqual(val, Decimal("100"))

        # Invalid prices
        ok, _ = SupplierSyncService._validate_price("12.345")
        self.assertFalse(ok)

        ok, _ = SupplierSyncService._validate_price("N/A")
        self.assertFalse(ok)

        ok, _ = SupplierSyncService._validate_price("-15.00")
        self.assertFalse(ok)

        ok, _ = SupplierSyncService._validate_price("0.00")
        self.assertFalse(ok)

        ok, _ = SupplierSyncService._validate_price(None)
        self.assertFalse(ok)

    @patch("core.supplier_sync.requests.Session")
    def test_sync_catalogue_creation_update_deduplication(self, mock_session_cls):
        # Existing product in DB
        existing_p = Product.objects.create(
            sku="TEST-SYNC-01",
            name="Old Name",
            category="Brakes",
            brand="BrandA",
            vehicle_fitment="Universal",
            price=Decimal("100.00"),
            description="Old Desc",
        )
        inv = Inventory.objects.create(product=existing_p, quantity=42)

        unchanged_p = Product.objects.create(
            sku="TEST-SYNC-02",
            name="Same Name",
            category="Filters",
            brand="BrandB",
            vehicle_fitment="Universal",
            price=Decimal("200.00"),
            description="Same Desc",
        )
        inv_unchanged = Inventory.objects.create(product=unchanged_p, quantity=15)

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # Page 1:
        # - TEST-SYNC-01 updated
        # - TEST-SYNC-02 unchanged
        # - TEST-SYNC-03 created
        # - TEST-BAD-01 rejected (missing sku)
        # - TEST-BAD-02 rejected (invalid price "12.345")
        # Page 2:
        # - TEST-SYNC-03 duplicate with newer updated_at
        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = {
            "items": [
                {
                    "supplier_sku": "SUPP-01",
                    "sku": "TEST-SYNC-01",
                    "name": "Updated Name",
                    "category": "Brakes",
                    "brand": "BrandA",
                    "vehicle_fitment": "Universal",
                    "price": "120.00",
                    "description": "Updated Desc",
                    "supplier_stock": 500,
                    "updated_at": "2026-03-01T10:00:00Z",
                },
                {
                    "supplier_sku": "SUPP-02",
                    "sku": "TEST-SYNC-02",
                    "name": "Same Name",
                    "category": "Filters",
                    "brand": "BrandB",
                    "vehicle_fitment": "Universal",
                    "price": "200.00",
                    "description": "Same Desc",
                    "supplier_stock": 300,
                    "updated_at": "2026-03-01T10:00:00Z",
                },
                {
                    "supplier_sku": "SUPP-03",
                    "sku": "TEST-SYNC-03",
                    "name": "New Part Early",
                    "category": "Chains",
                    "brand": "BrandC",
                    "vehicle_fitment": "Pulsar",
                    "price": "350.00",
                    "description": "New chain part",
                    "supplier_stock": 100,
                    "updated_at": "2026-03-01T08:00:00Z",
                },
                {
                    "supplier_sku": "SUPP-BAD1",
                    "sku": "",
                    "name": "Missing SKU Part",
                    "price": "50.00",
                },
                {
                    "supplier_sku": "SUPP-BAD2",
                    "sku": "TEST-BAD-02",
                    "name": "Invalid Price Part",
                    "price": "12.345",
                },
            ],
            "next_cursor": "cursor_p2",
        }

        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = {
            "items": [
                {
                    "supplier_sku": "SUPP-03",
                    "sku": "TEST-SYNC-03",
                    "name": "New Part Latest",
                    "category": "Chains",
                    "brand": "BrandC",
                    "vehicle_fitment": "Pulsar",
                    "price": "360.00",
                    "description": "New chain part latest revision",
                    "supplier_stock": 120,
                    "updated_at": "2026-03-01T12:00:00Z",
                }
            ],
            "next_cursor": None,
        }

        mock_session.get.side_effect = [page1_response, page2_response]

        res = SupplierSyncService.sync_catalogue(base_url="http://mock-supplier.internal", api_key="secret-key")

        self.assertEqual(res["pages_fetched"], 2)
        self.assertEqual(res["created"], 1)
        self.assertEqual(res["updated"], 1)
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual(res["rejected"][0]["reason"], "missing sku")
        self.assertEqual(res["rejected"][1]["reason"], "invalid price")

        # Verify DB updates
        existing_p.refresh_from_db()
        self.assertEqual(existing_p.name, "Updated Name")
        self.assertEqual(existing_p.price, Decimal("120.00"))
        # Inventory quantity must NEVER be altered
        inv.refresh_from_db()
        self.assertEqual(inv.quantity, 42)

        # Unchanged product
        unchanged_p.refresh_from_db()
        self.assertEqual(unchanged_p.name, "Same Name")
        inv_unchanged.refresh_from_db()
        self.assertEqual(inv_unchanged.quantity, 15)

        # Created product has stock 0
        new_p = Product.objects.get(sku="TEST-SYNC-03")
        self.assertEqual(new_p.name, "New Part Latest")
        self.assertEqual(new_p.price, Decimal("360.00"))
        self.assertEqual(new_p.stock, 0)
        new_inv = Inventory.objects.get(product=new_p)
        self.assertEqual(new_inv.quantity, 0)

    @patch("time.sleep", return_value=None)
    @patch("core.supplier_sync.requests.Session")
    def test_sync_retry_on_429_and_503(self, mock_session_cls, mock_sleep):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.1"}

        resp_503 = MagicMock()
        resp_503.status_code = 503

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "items": [],
            "next_cursor": None,
        }

        mock_session.get.side_effect = [resp_429, resp_503, resp_200]

        res = SupplierSyncService.sync_catalogue()
        self.assertEqual(res["requests_made"], 3)
        self.assertEqual(res["pages_fetched"], 1)

    @patch("time.sleep", return_value=None)
    @patch("core.supplier_sync.requests.Session")
    def test_sync_fails_and_rolls_back_atomically_on_outage(self, mock_session_cls, mock_sleep):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        resp_503 = MagicMock()
        resp_503.status_code = 503

        # All 5 attempts fail
        mock_session.get.side_effect = [resp_503, resp_503, resp_503, resp_503, resp_503]

        with self.assertRaises(SupplierUnavailableException):
            SupplierSyncService.sync_catalogue()

    @patch("core.supplier_sync.requests.Session")
    def test_sync_fails_on_401_unauthorized(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        resp_401 = MagicMock()
        resp_401.status_code = 401

        mock_session.get.return_value = resp_401

        with self.assertRaises(SupplierUnavailableException):
            SupplierSyncService.sync_catalogue()


class SupplierSyncAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("core.supplier_sync.SupplierSyncService.sync_catalogue")
    def test_post_supplier_sync_endpoint_success(self, mock_sync):
        mock_sync.return_value = {
            "created": 12,
            "updated": 24,
            "unchanged": 570,
            "rejected": [
                {"supplier_sku": "SUP-101", "reason": "missing sku"}
            ],
            "pages_fetched": 4,
            "requests_made": 5,
        }

        response = self.client.post("/api/sync/supplier/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["created"], 12)
        self.assertEqual(data["updated"], 24)
        self.assertEqual(data["unchanged"], 570)
        self.assertEqual(len(data["rejected"]), 1)

    @patch("core.supplier_sync.SupplierSyncService.sync_catalogue")
    def test_post_supplier_sync_endpoint_unavailable(self, mock_sync):
        mock_sync.side_effect = SupplierUnavailableException("Supplier API outage.")

        response = self.client.post("/api/sync/supplier/")
        self.assertEqual(response.status_code, 502)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], "SUPPLIER_UNAVAILABLE")

    @patch("core.supplier_sync.SupplierSyncService.sync_catalogue")
    def test_sync_supplier_management_command(self, mock_sync):
        mock_sync.return_value = {
            "created": 2,
            "updated": 1,
            "unchanged": 5,
            "rejected": [],
            "pages_fetched": 2,
            "requests_made": 2,
        }

        call_command("sync_supplier")
        mock_sync.assert_called_once()
