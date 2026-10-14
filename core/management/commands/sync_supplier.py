from django.core.management.base import BaseCommand
from core.supplier_sync import SupplierSyncService


class Command(BaseCommand):
    help = "Synchronize catalogue and pricing with supplier API according to API contract section 8."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            default=None,
            help="Supplier API base URL override.",
        )
        parser.add_argument(
            "--key",
            type=str,
            default=None,
            help="Supplier API key override.",
        )

    def handle(self, *args, **options):
        self.stdout.write("Starting supplier catalogue synchronization...")
        try:
            result = SupplierSyncService.sync_catalogue(
                base_url=options.get("url"),
                api_key=options.get("key"),
            )
            self.stdout.write(self.style.SUCCESS(
                f"Sync complete: created={result['created']} updated={result['updated']} "
                f"unchanged={result['unchanged']} rejected={len(result['rejected'])} "
                f"pages_fetched={result['pages_fetched']} requests_made={result['requests_made']}"
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Sync failed: {e}"))
            raise

