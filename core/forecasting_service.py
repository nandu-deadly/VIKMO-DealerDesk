import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from django.conf import settings
from core.models import Product, Inventory
from core.exceptions import NotFoundException


class ForecastingService:
    @staticmethod
    def get_forecast_file_path() -> Path:
        return settings.BASE_DIR / "ml" / "forecast.csv"

    @staticmethod
    def get_lead_times_file_path() -> Path:
        data_dir = getattr(settings, "DATA_DIR", settings.BASE_DIR / "data")
        return data_dir / "lead_times.csv"

    @staticmethod
    def get_sales_history_file_path() -> Path:
        data_dir = getattr(settings, "DATA_DIR", settings.BASE_DIR / "data")
        return data_dir / "sales_history.csv"

    @classmethod
    def load_forecasts(cls) -> dict[str, list[dict]]:
        """Loads ml/forecast.csv and returns {sku: [{'week_start': '...', 'forecast_units': float}, ...]}"""
        path = cls.get_forecast_file_path()
        if not path.exists():
            return {}

        forecasts = defaultdict(list)
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                sku = r.get("sku")
                week = r.get("week_start")
                if not sku or not week:
                    continue
                try:
                    units = max(0.0, float(r.get("forecast_units", 0.0)))
                except (ValueError, TypeError):
                    units = 0.0
                forecasts[sku].append({"week_start": week, "forecast_units": units})
        return dict(forecasts)

    @classmethod
    def load_lead_times(cls) -> dict[str, int]:
        """Loads data/lead_times.csv and returns {sku: lead_time_weeks}"""
        path = cls.get_lead_times_file_path()
        if not path.exists():
            return {}

        lead_times = {}
        with open(path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sku = r.get("sku")
                if not sku:
                    continue
                try:
                    lt = int(r.get("lead_time_weeks", 1))
                except (ValueError, TypeError):
                    lt = 1
                lead_times[sku] = max(1, lt)
        return lead_times

    @classmethod
    def load_recent_sales_sigma(cls) -> dict[str, float]:
        """Calculates sample std dev (ddof=1) of units_sold over most recent 12 weeks per SKU."""
        path = cls.get_sales_history_file_path()
        if not path.exists():
            return {}

        sales_by_sku = defaultdict(list)
        with open(path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sku = r.get("sku")
                week = r.get("week_start")
                if not sku or not week:
                    continue
                try:
                    units = float(r.get("units_sold", 0.0))
                except (ValueError, TypeError):
                    units = 0.0
                sales_by_sku[sku].append((week, max(0.0, units)))

        sigmas = {}
        for sku, records in sales_by_sku.items():
            records.sort(key=lambda x: x[0])
            recent = [x[1] for x in records[-12:]]
            if len(recent) > 1:
                sigmas[sku] = statistics.stdev(recent)
            else:
                sigmas[sku] = 0.0
        return sigmas

    @classmethod
    def get_sku_forecast(cls, sku: str) -> dict:
        lead_times = cls.load_lead_times()
        if sku not in lead_times:
            raise NotFoundException(f"Forecast for SKU '{sku}' not found.")
        forecasts = cls.load_forecasts()
        if sku not in forecasts:
            raise NotFoundException(f"Forecast for SKU '{sku}' not found.")
        return {
            "sku": sku,
            "forecast": forecasts[sku][:4],
        }

    @classmethod
    def get_reorder_suggestions(cls) -> list[dict]:
        lead_times = cls.load_lead_times()
        forecasts = cls.load_forecasts()
        sigmas = cls.load_recent_sales_sigma()

        # Query live inventory quantity from PostgreSQL
        live_stock_map = {
            inv.product_id: inv.quantity
            for inv in Inventory.objects.filter(product_id__in=lead_times.keys())
        }

        results = []
        for sku, lead_time_weeks in lead_times.items():
            raw_stock = live_stock_map.get(sku, 0)
            current_stock = max(0, int(raw_stock)) if raw_stock is not None else 0
            sku_forecast = forecasts.get(sku, [])

            # lead_time_demand = sum of forecast_units for the first L forecast weeks
            l_weeks = min(lead_time_weeks, len(sku_forecast))
            lead_time_demand = round(sum(f["forecast_units"] for f in sku_forecast[:l_weeks]), 1)

            # sigma = sample standard deviation over most recent 12 weeks
            sigma = sigmas.get(sku, 0.0)

            # safety_stock = ceil(1.65 * sigma * sqrt(L))
            safety_stock = math.ceil(1.65 * sigma * math.sqrt(lead_time_weeks))

            # reorder_point = lead_time_demand + safety_stock
            reorder_point = round(lead_time_demand + safety_stock, 1)

            # reorder_qty = max(0, ceil(reorder_point - current_stock))
            reorder_qty = max(0, math.ceil(reorder_point - current_stock))

            results.append({
                "sku": sku,
                "current_stock": current_stock,
                "lead_time_weeks": lead_time_weeks,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "reorder_qty": reorder_qty,
            })

        return results

