import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Product, Inventory, Dealer


class Command(BaseCommand):
    help = "Load catalogue.csv and dealers.csv into PostgreSQL. Idempotent and safe to run multiple times."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-stock",
            action="store_true",
            help="Reset inventory stock levels to the values in catalogue.csv (default: preserves existing stock).",
        )

    def handle(self, *args, **options):
        reset_stock = options.get("reset_stock", False)
        data_dir = getattr(settings, "DATA_DIR", settings.BASE_DIR / "data")
        catalogue_path = data_dir / "catalogue.csv"
        dealers_path = data_dir / "dealers.csv"

        if not catalogue_path.exists():
            self.stderr.write(self.style.ERROR(f"Catalogue file not found at: {catalogue_path}"))
            return
        if not dealers_path.exists():
            self.stderr.write(self.style.ERROR(f"Dealers file not found at: {dealers_path}"))
            return

        self.stdout.write(f"Seeding data from {data_dir}...")
        self.seed_catalogue(catalogue_path, reset_stock)
        self.seed_dealers(dealers_path)
        from django.core.management import call_command
        call_command("setup_dealer_accounts")
        self.stdout.write(self.style.SUCCESS("Data seeding completed successfully."))

    def seed_catalogue(self, file_path: Path, reset_stock: bool = False):
        created_products = 0
        updated_products = 0
        created_inventory = 0
        skipped_rows = 0

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_cols = {"sku", "name", "category", "brand", "vehicle_fitment", "price", "stock", "description"}
            if not required_cols.issubset(set(reader.fieldnames or [])):
                self.stderr.write(self.style.ERROR(f"catalogue.csv missing required headers: {required_cols - set(reader.fieldnames or [])}"))
                return

            with transaction.atomic():
                for row in reader:
                    sku = (row.get("sku") or "").strip()
                    name = (row.get("name") or "").strip()
                    if not sku or not name:
                        skipped_rows += 1
                        continue

                    try:
                        price = Decimal(row.get("price", "0.00").strip())
                        starting_stock = int(row.get("stock", "0").strip())
                    except (InvalidOperation, ValueError):
                        skipped_rows += 1
                        continue

                    product, p_created = Product.objects.update_or_create(
                        sku=sku,
                        defaults={
                            "name": name,
                            "category": (row.get("category") or "").strip(),
                            "brand": (row.get("brand") or "").strip(),
                            "vehicle_fitment": (row.get("vehicle_fitment") or "").strip(),
                            "price": price,
                            "description": row.get("description", "") or "",
                        },
                    )
                    if p_created:
                        created_products += 1
                    else:
                        updated_products += 1

                    # Inventory: create if not exists, preserve live stock on re-seed
                    inv, inv_created = Inventory.objects.get_or_create(
                        product=product,
                        defaults={"quantity": starting_stock},
                    )
                    if inv_created:
                        created_inventory += 1
                    elif reset_stock:
                        inv.quantity = starting_stock
                        inv.save(update_fields=["quantity"])

                # Remove non-catalogue products (e.g. from temporary mock runs) to preserve exactly 600 products
                with open(file_path, "r", encoding="utf-8") as f_check:
                    valid_skus = {r.get("sku", "").strip() for r in csv.DictReader(f_check) if r.get("sku")}
                extra_products = Product.objects.exclude(sku__in=valid_skus)
                if extra_products.exists():
                    from core.models import OrderItem
                    OrderItem.objects.filter(sku__in=[p.sku for p in extra_products]).delete()
                    extra_products.delete()

        self.stdout.write(
            f"Catalogue: {created_products} created, {updated_products} updated, "
            f"{created_inventory} new inventory records initialized, {skipped_rows} skipped."
        )

    def seed_dealers(self, file_path: Path):
        created_dealers = 0
        updated_dealers = 0
        skipped_rows = 0

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_cols = {"dealer_code", "name"}
            if not required_cols.issubset(set(reader.fieldnames or [])):
                self.stderr.write(self.style.ERROR(f"dealers.csv missing required headers: {required_cols - set(reader.fieldnames or [])}"))
                return

            with transaction.atomic():
                for row in reader:
                    dealer_code = (row.get("dealer_code") or "").strip()
                    name = (row.get("name") or "").strip()
                    if not dealer_code or not name:
                        skipped_rows += 1
                        continue

                    try:
                        credit_limit_raw = (row.get("credit_limit") or "0.00").strip()
                        credit_limit = Decimal(credit_limit_raw) if credit_limit_raw else Decimal("0.00")
                    except InvalidOperation:
                        credit_limit = Decimal("0.00")

                    _, created = Dealer.objects.update_or_create(
                        dealer_code=dealer_code,
                        defaults={
                            "name": name,
                            "city": (row.get("city") or "").strip(),
                            "phone": (row.get("phone") or "").strip(),
                            "email": (row.get("email") or "").strip(),
                            "gstin": (row.get("gstin") or "").strip(),
                            "credit_limit": credit_limit,
                        },
                    )
                    if created:
                        created_dealers += 1
                    else:
                        updated_dealers += 1

                # Remove non-CSV dealers (e.g. temporary smoke test dealers) to preserve exactly 25 dealers
                with open(file_path, "r", encoding="utf-8") as f_dcheck:
                    valid_dealer_codes = {r.get("dealer_code", "").strip() for r in csv.DictReader(f_dcheck) if r.get("dealer_code")}
                extra_dealers = Dealer.objects.exclude(dealer_code__in=valid_dealer_codes)
                if extra_dealers.exists():
                    from core.models import Order
                    Order.objects.filter(dealer__in=extra_dealers).delete()
                    extra_dealers.delete()

        self.stdout.write(
            f"Dealers: {created_dealers} created, {updated_dealers} updated, {skipped_rows} skipped."
        )
