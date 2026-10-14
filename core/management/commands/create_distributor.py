import os
import sys
from getpass import getpass
from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Create or update a Distributor operations user account with staff role. "
        "Securely accepts credentials via hidden prompt or DISTRIBUTOR_PASSWORD env var. "
        "Does not overwrite existing passwords unless --reset-password is explicitly specified."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            help="Distributor username (default: DISTRIBUTOR_USERNAME env or 'distributor')",
        )
        parser.add_argument(
            "--password",
            type=str,
            help="Distributor password (optional; prefer DISTRIBUTOR_PASSWORD env var or hidden prompt)",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="",
            help="Distributor email address (default: DISTRIBUTOR_EMAIL env or 'distributor@vikmo.internal')",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Force updating/resetting the password on an existing distributor account",
        )

    def handle(self, *args, **options):
        dist_group, _ = Group.objects.get_or_create(name="Distributor")

        username = (options.get("username") or os.environ.get("DISTRIBUTOR_USERNAME") or "distributor").strip()
        email = options.get("email") or os.environ.get("DISTRIBUTOR_EMAIL") or "distributor@vikmo.internal"
        reset_password = options.get("reset_password", False)
        cli_password = options.get("password") or os.environ.get("DISTRIBUTOR_PASSWORD")

        user_exists = User.objects.filter(username=username).exists()

        if user_exists and not reset_password and not cli_password:
            # Idempotently ensure roles and permissions without modifying user's existing password
            user = User.objects.get(username=username)
            needs_save = False

            if not user.is_staff:
                user.is_staff = True
                needs_save = True

            if needs_save:
                user.save(update_fields=["is_staff"])

            if not user.groups.filter(name="Distributor").exists():
                user.groups.add(dist_group)

            # Audit against known legacy default passwords
            known_defaults = ["Distributor@123", "Distributor@2026Safe", "admin", "password"]
            uses_default = any(user.check_password(d) for d in known_defaults)
            if uses_default:
                self.stdout.write(
                    self.style.WARNING(
                        f"SECURITY NOTICE: Distributor account '{username}' is currently using a known default credential. "
                        f"Run with '--reset-password' or set DISTRIBUTOR_PASSWORD to rotate the credential."
                    )
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Distributor account '{username}' already exists. Preserved existing password and verified Distributor role."
                )
            )
            return

        # Password is required when creating a new user or when explicitly resetting password
        password = cli_password
        if not password:
            if sys.stdin.isatty():
                prompt_label = f"Enter password for distributor '{username}': "
                password = getpass(prompt_label).strip()
                if not password:
                    raise CommandError("Password cannot be empty.")
                confirm = getpass("Confirm password: ").strip()
                if password != confirm:
                    raise CommandError("Passwords do not match.")
            else:
                raise CommandError(
                    f"Password required to {'reset' if user_exists else 'create'} distributor account '{username}'. "
                    "Supply via DISTRIBUTOR_PASSWORD environment variable or interactive prompt."
                )

        if len(password) < 8:
            raise CommandError("Distributor password must be at least 8 characters long.")

        with transaction.atomic():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "is_staff": True,
                    "is_superuser": False,
                    "email": email,
                },
            )
            user.set_password(password)
            user.is_staff = True
            if email and user.email != email:
                user.email = email
            user.save()

            if not user.groups.filter(name="Distributor").exists():
                user.groups.add(dist_group)

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} distributor account '{username}' successfully (is_staff=True, group=Distributor)."
            )
        )
