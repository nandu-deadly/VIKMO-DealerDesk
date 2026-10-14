from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Dealer


class Command(BaseCommand):
    help = "Create or link 25 Django auth accounts for dealers DLR-001 to DLR-025 with hashed passwords."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset existing dealer accounts to their initial passwords (default: preserves existing passwords).",
        )

    def handle(self, *args, **options):
        reset_passwords = options.get("reset_passwords", False)
        dealer_group, _ = Group.objects.get_or_create(name="Dealer")

        created_count = 0
        linked_count = 0
        existing_count = 0

        self.stdout.write("Setting up 25 Dealer authentication accounts...")

        with transaction.atomic():
            for num in range(1, 26):
                code = f"DLR-{num:03d}"
                initial_password = f"Dealer@{num:03d}"

                dealer = Dealer.objects.filter(dealer_code=code).first()
                if not dealer:
                    self.stderr.write(self.style.WARNING(f"Dealer with code {code} not found in database. Skipping."))
                    continue

                user = User.objects.filter(username=code).first()
                if not user:
                    user = User.objects.create_user(
                        username=code,
                        password=initial_password,
                        first_name=dealer.name[:30],
                        email=dealer.email or "",
                    )
                    user.groups.add(dealer_group)
                    created_count += 1
                else:
                    existing_count += 1
                    if reset_passwords:
                        user.set_password(initial_password)
                        user.save()
                    if not user.groups.filter(name="Dealer").exists():
                        user.groups.add(dealer_group)

                # Link Dealer to User if not already linked
                if dealer.user_id != user.id:
                    dealer.user = user
                    dealer.save(update_fields=["user"])
                    linked_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Dealer accounts setup completed: {created_count} created, "
                f"{linked_count} linked to Dealer profiles, {existing_count} existing accounts preserved."
            )
        )
