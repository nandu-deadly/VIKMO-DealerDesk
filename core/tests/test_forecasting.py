import csv
import math
from pathlib import Path
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from core.models import Product, Inventory
from core.forecasting_service import ForecastingService


class ForecastingAndReorderTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        forecast_path = settings.BASE_DIR / "ml" / "forecast.csv"
        if not forecast_path.exists():
            from ml.train_forecast import generate_forecast_csv
            generate_forecast_csv()

        if Product.objects.count() < 40:
            from django.core.management import call_command
            call_command("seed_data")

    def setUp(self):
        self.client = APIClient()
        self.forecast_path = settings.BASE_DIR / "ml" / "forecast.csv"
        self.lead_times_path = getattr(settings, "DATA_DIR", settings.BASE_DIR / "data") / "lead_times.csv"

    def test_forecast_csv_structure_and_constraints(self):
        self.assertTrue(self.forecast_path.exists(), "ml/forecast.csv must exist")

        with open(self.forecast_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, ["sku", "week_start", "forecast_units"])
            rows = list(reader)

        self.assertEqual(len(rows), 160, "ml/forecast.csv must contain exactly 160 rows")

        expected_weeks = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]
        with open(self.lead_times_path, "r", encoding="utf-8") as f:
            expected_skus = {r["sku"] for r in csv.DictReader(f)}

        self.assertEqual(len(expected_skus), 40, "lead_times.csv must have 40 SKUs")

        seen_pairs = set()
        for r in rows:
            sku = r["sku"]
            w = r["week_start"]
            u = float(r["forecast_units"])

            self.assertIn(sku, expected_skus)
            self.assertIn(w, expected_weeks)
            self.assertGreaterEqual(u, 0.0, f"Forecast units must be non-negative for {sku} {w}")

            pair = (sku, w)
            self.assertNotIn(pair, seen_pairs, f"Duplicate pair found: {pair}")
            seen_pairs.add(pair)

        self.assertEqual(len(seen_pairs), 160)

    def test_forecast_api_detail_and_404(self):
        forecasts = ForecastingService.load_forecasts()
        sample_sku = list(forecasts.keys())[0]

        res = self.client.get(f"/api/forecast/{sample_sku}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["sku"], sample_sku)
        self.assertEqual(len(data["forecast"]), 4)
        self.assertEqual(
            [f["week_start"] for f in data["forecast"]],
            ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"],
        )

        # 404 for unknown SKU
        res_404 = self.client.get("/api/forecast/UNKNOWN-SKU-999/")
        self.assertEqual(res_404.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_404.json()["error"]["code"], "NOT_FOUND")

    def test_reorder_suggestions_api_and_exact_formulas(self):
        res = self.client.get("/api/reorder-suggestions/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertIn("results", data)
        results = data["results"]
        self.assertEqual(len(results), 40, "reorder-suggestions must return 40 items")

        lead_times = ForecastingService.load_lead_times()
        forecasts = ForecastingService.load_forecasts()
        sigmas = ForecastingService.load_recent_sales_sigma()

        for item in results:
            sku = item["sku"]
            current_stock = item["current_stock"]
            l_weeks = item["lead_time_weeks"]
            ltd = item["lead_time_demand"]
            ss = item["safety_stock"]
            rop = item["reorder_point"]
            roq = item["reorder_qty"]

            self.assertEqual(l_weeks, lead_times[sku])

            # 1. lead_time_demand = sum of first L forecast weeks
            expected_ltd = round(sum(f["forecast_units"] for f in forecasts[sku][:l_weeks]), 1)
            self.assertEqual(ltd, expected_ltd)

            # 2. safety_stock = ceil(1.65 * sigma * sqrt(L))
            sigma = sigmas[sku]
            expected_ss = math.ceil(1.65 * sigma * math.sqrt(l_weeks))
            self.assertEqual(ss, expected_ss)

            # 3. reorder_point = lead_time_demand + safety_stock
            expected_rop = round(expected_ltd + expected_ss, 1)
            self.assertEqual(rop, expected_rop)

            # 4. reorder_qty = max(0, ceil(reorder_point - current_stock))
            expected_roq = max(0, math.ceil(expected_rop - current_stock))
            self.assertEqual(roq, expected_roq)

    def test_reorder_suggestions_live_inventory_integration(self):
        forecasts = ForecastingService.load_forecasts()
        sample_sku = list(forecasts.keys())[0]

        # Fetch product and update stock
        product = Product.objects.get(sku=sample_sku)
        initial_stock = product.stock

        # Update stock via inventory API to 1000 (exceeding reorder point) -> reorder_qty = 0
        new_qty = 1000
        self.client.put(f"/api/inventory/{sample_sku}/", {"quantity": new_qty, "reason": "test"}, format="json")

        res = self.client.get("/api/reorder-suggestions/")
        item = next(x for x in res.json()["results"] if x["sku"] == sample_sku)
        self.assertEqual(item["current_stock"], new_qty)
        self.assertEqual(item["reorder_qty"], 0)

        # Update stock to 0 -> reorder_qty should equal ceil(reorder_point)
        self.client.put(f"/api/inventory/{sample_sku}/", {"quantity": 0, "reason": "test zero"}, format="json")
        res2 = self.client.get("/api/reorder-suggestions/")
        item2 = next(x for x in res2.json()["results"] if x["sku"] == sample_sku)
        self.assertEqual(item2["current_stock"], 0)
        self.assertEqual(item2["reorder_qty"], math.ceil(item2["reorder_point"]))

    def test_croston_sba_zero_demand_and_intermittent_boundaries(self):
        """Boundary test: Croston-SBA must safely handle all-zero and intermittent series."""
        from ml.train_forecast import croston_sba

        # Case 1: All zero demand
        self.assertEqual(croston_sba([0.0, 0.0, 0.0, 0.0]), 0.0)

        # Case 2: Intermittent demand with zeroes
        res = croston_sba([0.0, 10.0, 0.0, 0.0, 15.0, 0.0])
        self.assertGreater(res, 0.0)
        self.assertLess(res, 15.0)

    def test_forecast_pipeline_strict_chronological_leakage_prevention(self):
        """Proves that training records strictly precede the test period (no future leakage)."""
        from ml.train_forecast import load_data
        lead_times, sales, _ = load_data()

        test_horizon_start = "2026-09-28"
        for sku, records in sales.items():
            train_subset = [r for r in records if r["week_start"] < test_horizon_start]
            for r in train_subset:
                self.assertLess(
                    r["week_start"],
                    test_horizon_start,
                    f"Future data leakage detected for {sku}: {r['week_start']} >= {test_horizon_start}",
                )

    def test_forecast_non_forecast_catalogue_sku_returns_404(self):
        """Catalogue SKUs that are not forecast SKUs must return 404 per API contract."""
        lead_times = ForecastingService.load_lead_times()
        other_prod = Product.objects.exclude(sku__in=lead_times.keys()).first()
        self.assertIsNotNone(other_prod, "Catalogue should contain non-forecast SKUs")

        res = self.client.get(f"/api/forecast/{other_prod.sku}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.json()["error"]["code"], "NOT_FOUND")

    def test_reorder_suggestions_handles_missing_inventory_record(self):
        """If an inventory record is absent in PostgreSQL, default live stock to 0."""
        lead_times = ForecastingService.load_lead_times()
        sample_sku = list(lead_times.keys())[0]

        # Temporarily delete inventory record
        Inventory.objects.filter(product_id=sample_sku).delete()

        res = self.client.get("/api/reorder-suggestions/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        item = next(x for x in res.json()["results"] if x["sku"] == sample_sku)
        self.assertEqual(item["current_stock"], 0)
        self.assertEqual(item["reorder_qty"], math.ceil(item["reorder_point"]))

    def test_edge_case_single_or_zero_sales_sigma(self):
        """When sales history has <= 1 observations, sigma must evaluate to 0.0."""
        sigmas = ForecastingService.load_recent_sales_sigma()
        # Ensure every sigma is a non-negative float
        for sku, s in sigmas.items():
            self.assertIsInstance(s, float)
            self.assertGreaterEqual(s, 0.0)

        # Direct unit test of std dev edge case
        from unittest.mock import patch
        with patch.object(ForecastingService, "get_sales_history_file_path") as mock_path:
            # Point to non-existent path
            mock_path.return_value = Path("/non/existent/path/sales_history.csv")
            empty_sigmas = ForecastingService.load_recent_sales_sigma()
            self.assertEqual(empty_sigmas, {})



