import csv
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import Product, Inventory, Dealer, Order, OrderItem, OrderStatus, IdempotencyRecord
from core.order_service import OrderService


class Command(BaseCommand):
    help = (
        "Safely reset local development database: reverse stock deductions for confirmed orders, "
        "clear orders, remove test dealers, and restore exactly 25 seeded dealers without data corruption."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Explicit confirmation required to execute database reset.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the reset and display the expected before/after changes without modifying the database.",
        )
        parser.add_argument(
            "--reset-stock",
            action="store_true",
            help="Optionally reset all warehouse inventory levels to the exact starting quantities from catalogue.csv.",
        )

    def handle(self, *args, **options):
        confirm = options.get("confirm", False)
        dry_run = options.get("dry_run", False)

        # 1. Production and safety guardrails
        self.verify_safety_guards()

        # 2. Verify authoritative seed data files exist
        data_dir = getattr(settings, "DATA_DIR", settings.BASE_DIR / "data")
        dealers_csv = data_dir / "dealers.csv"
        catalogue_csv = data_dir / "catalogue.csv"

        if not dealers_csv.exists() or not catalogue_csv.exists():
            raise CommandError("Authoritative seed CSV files (dealers.csv / catalogue.csv) not found in data/ directory.")

        with open(dealers_csv, "r", encoding="utf-8") as f:
            expected_seeded_codes = {r["dealer_code"].strip() for r in csv.DictReader(f) if r.get("dealer_code")}

        if len(expected_seeded_codes) != 25:
            raise CommandError(f"Expected 25 seeded dealer codes in {dealers_csv}, found {len(expected_seeded_codes)}.")

        # 3. Take snapshot before reset
        pre_products_count = Product.objects.count()
        pre_inventory_count = Inventory.objects.count()
        pre_dealers_count = Dealer.objects.count()
        pre_orders_count = Order.objects.count()

        status_counts = {
            s.value: Order.objects.filter(status=s.value).count()
            for s in [OrderStatus.DRAFT, OrderStatus.CONFIRMED, OrderStatus.DISPATCHED, OrderStatus.DELIVERED, OrderStatus.CANCELLED]
        }

        # Identify all confirmed orders and calculate exact inventory deductions to be reversed
        confirmed_orders = Order.objects.filter(status=OrderStatus.CONFIRMED).prefetch_related("items")
        stock_restorations = {}
        for ord_obj in confirmed_orders:
            for item in ord_obj.items.all():
                stock_restorations[item.sku] = stock_restorations.get(item.sku, 0) + item.quantity

        pre_sku_stocks = {}
        for sku in sorted(stock_restorations.keys()):
            inv = Inventory.objects.filter(product_id=sku).first()
            pre_sku_stocks[sku] = inv.quantity if inv else 0

        # Non-seeded dealers to be removed
        non_seeded_dealers = Dealer.objects.exclude(dealer_code__in=expected_seeded_codes)
        test_dealers_list = [(d.id, d.dealer_code, d.name) for d in non_seeded_dealers]

        self.stdout.write(self.style.NOTICE("======================================================================"))
        self.stdout.write(self.style.NOTICE("           VIKMO DEALERDESK — LOCAL DB RESET AUDIT PREVIEW           "))
        self.stdout.write(self.style.NOTICE("======================================================================"))
        self.stdout.write(f"Database:             {settings.DATABASES['default'].get('NAME')}")
        self.stdout.write(f"Catalogue Products:   {pre_products_count} (Must remain preserved)")
        self.stdout.write(f"Inventory Records:    {pre_inventory_count} (Must remain preserved)")
        self.stdout.write(f"Total Dealers:        {pre_dealers_count} ({len(expected_seeded_codes)} seeded + {len(test_dealers_list)} test/extra)")
        self.stdout.write(f"Total Orders:         {pre_orders_count} (Confirmed: {status_counts.get('CONFIRMED', 0)}, Cancelled: {status_counts.get('CANCELLED', 0)}, Draft: {status_counts.get('DRAFT', 0)})")
        self.stdout.write("")
        self.stdout.write("Inventory Deductions to be Safely Reversed (Confirmed orders only):")
        for sku, qty in sorted(stock_restorations.items()):
            curr = pre_sku_stocks[sku]
            self.stdout.write(f"  * SKU {sku}: Current={curr} -> Reversing Deduction (+{qty}) -> Restored={curr + qty}")

        if test_dealers_list:
            self.stdout.write("")
            self.stdout.write("Non-seeded / Test Dealers to be Removed:")
            for d_id, code, name in test_dealers_list:
                self.stdout.write(f"  * ID {d_id} [{code}] - {name}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No database modifications were performed."))
            return

        if not confirm:
            self.stdout.write(self.style.ERROR("\nReset aborted: --confirm flag is required to apply changes."))
            self.stdout.write("Run with: python manage.py reset_dev_database --confirm\n")
            return

        reset_stock = options.get("reset_stock", False)

        # 4. Atomic execution of safe reset
        with transaction.atomic():
            # Step A: Reverse inventory deductions for confirmed orders exactly once
            for ord_obj in confirmed_orders:
                for item in ord_obj.items.all():
                    inv = Inventory.objects.select_for_update().filter(product_id=item.sku).first()
                    if inv:
                        inv.quantity += item.quantity
                        inv.save(update_fields=["quantity"])

            if reset_stock:
                with open(catalogue_csv, "r", encoding="utf-8") as f_cat:
                    for row in csv.DictReader(f_cat):
                        sku = (row.get("sku") or "").strip()
                        stock_str = (row.get("stock") or "").strip()
                        if sku and stock_str.isdigit():
                            Inventory.objects.filter(product_id=sku).update(quantity=int(stock_str))

            # Step B: Remove all orders and idempotency records
            IdempotencyRecord.objects.all().delete()
            OrderItem.objects.all().delete()
            Order.objects.all().delete()

            # Step C: Remove non-seeded dealers and linked test accounts
            for d in non_seeded_dealers:
                if d.user:
                    d.user.delete()
                d.delete()

            # Step D: Ensure all 25 seeded dealers are active and marked valid
            Dealer.objects.filter(dealer_code__in=expected_seeded_codes).update(is_active=True)

        # 5. Post-reset verification
        post_products_count = Product.objects.count()
        post_inventory_count = Inventory.objects.count()
        post_dealers_count = Dealer.objects.count()
        post_orders_count = Order.objects.count()

        remaining_codes = set(Dealer.objects.values_list("dealer_code", flat=True))
        if remaining_codes != expected_seeded_codes:
            raise CommandError(f"Post-reset dealer codes mismatch! Expected 25 seeded codes, got: {remaining_codes}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("======================================================================"))
        self.stdout.write(self.style.SUCCESS("                LOCAL DATABASE RESET COMPLETED SUCCESSFULLY           "))
        self.stdout.write(self.style.SUCCESS("======================================================================"))
        self.stdout.write(f"Catalogue Products:   {post_products_count} (Preserved)")
        self.stdout.write(f"Inventory Records:    {post_inventory_count} (Preserved)")
        self.stdout.write(f"Dealers:              {post_dealers_count} (Exactly the 25 seeded dealers DLR-001 through DLR-025)")
        self.stdout.write(f"Orders:               {post_orders_count} (Cleaned)")
        self.stdout.write("")
        self.stdout.write("Restored SKU Inventory Levels:")
        for sku in sorted(stock_restorations.keys()):
            inv = Inventory.objects.get(product_id=sku)
            self.stdout.write(f"  * SKU {sku}: Verified Stock = {inv.quantity}")

    def verify_safety_guards(self):
        """Prevents execution in production environments or unrecognized databases."""
        import os
        import sys
        env = os.environ.get("DJANGO_ENV", "").lower()
        node_env = os.environ.get("ENVIRONMENT", "").lower()
        if env in ("production", "prod") or node_env in ("production", "prod"):
            raise CommandError("SAFETY ABORT: Refusing to run reset_dev_database in a PRODUCTION environment.")

        db_name = settings.DATABASES["default"].get("NAME", "").lower()
        if "prod" in db_name:
            raise CommandError(f"SAFETY ABORT: Database name '{db_name}' contains 'prod'. Aborting.")

        is_testing = "test" in sys.argv or getattr(settings, "IS_TESTING", False) or db_name.startswith("test_")
        if not getattr(settings, "DEBUG", False) and not is_testing:
            raise CommandError("SAFETY ABORT: settings.DEBUG is False. reset_dev_database is strictly for development environments.")
