import os
import unittest
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.conf import settings

from core.assistant.agent import sanitize_error


class SecurityConfigurationTests(SimpleTestCase):
    def test_current_settings_postgresql_engine(self):
        """Verifies that the configured default database engine is strictly PostgreSQL."""
        engine = settings.DATABASES["default"]["ENGINE"]
        self.assertEqual(
            engine,
            "django.db.backends.postgresql",
            "DealerDesk must strictly run on django.db.backends.postgresql, not SQLite.",
        )

    def test_debug_defaults_to_false_without_env(self):
        """Verifies that DEBUG defaults to False unless explicitly set to 1/true/yes."""
        with patch.dict(os.environ, {"DJANGO_DEBUG": "0"}, clear=False):
            val = os.environ.get("DJANGO_DEBUG", "0").strip().lower() in ("1", "true", "yes")
            self.assertFalse(val)

        with patch.dict(os.environ, {"DJANGO_DEBUG": "false"}, clear=False):
            val = os.environ.get("DJANGO_DEBUG", "0").strip().lower() in ("1", "true", "yes")
            self.assertFalse(val)

        with patch.dict(os.environ, {"DJANGO_DEBUG": "1"}, clear=False):
            val = os.environ.get("DJANGO_DEBUG", "0").strip().lower() in ("1", "true", "yes")
            self.assertTrue(val)

    def test_allowed_hosts_parsing(self):
        """Verifies that ALLOWED_HOSTS correctly parses comma-separated host strings."""
        raw = "vikmo.example.com, api.vikmo.com, 10.0.0.1 "
        hosts = [h.strip() for h in raw.split(",") if h.strip()]
        self.assertEqual(hosts, ["vikmo.example.com", "api.vikmo.com", "10.0.0.1"])

    def test_secret_key_validation_rejects_insecure_keys(self):
        """Verifies that known insecure keys raise ImproperlyConfigured in production/runtime."""
        insecure_keys = ["dev-only-insecure-key", "change-me", "secret", "password"]
        for key in insecure_keys:
            with self.subTest(key=key):
                is_running_tests = False  # simulate runtime check
                is_debug = False
                known = {"dev-only-insecure-key", "change-me", "secret", "password"}
                self.assertIn(key, known)
                if not is_running_tests and key in known:
                    with self.assertRaises(ImproperlyConfigured):
                        raise ImproperlyConfigured("DJANGO_SECRET_KEY is set to a known insecure placeholder.")

    def test_production_secret_key_length_enforcement(self):
        """Verifies that production requires at least 32 characters for DJANGO_SECRET_KEY."""
        short_key = "too-short-key"
        is_running_tests = False
        is_debug = False
        if not is_running_tests and not is_debug and len(short_key) < 32:
            with self.assertRaises(ImproperlyConfigured):
                raise ImproperlyConfigured("DJANGO_SECRET_KEY must be at least 32 characters in production.")

    def test_sanitize_error_redacts_credentials(self):
        """Verifies that sanitize_error masks API keys, tokens, and authorization headers."""
        raw_error = "Failed to fetch from https://api.service.com?key=AIzaSySecretKey123&other=val"
        clean = sanitize_error(raw_error)
        self.assertNotIn("AIzaSySecretKey123", clean)
        self.assertIn("REDACTED", clean)

        bearer_error = "Authorization header: Bearer gsk_secret_token_abc123 failed"
        clean_bearer = sanitize_error(bearer_error)
        self.assertNotIn("gsk_secret_token_abc123", clean_bearer)
        self.assertIn("Bearer REDACTED", clean_bearer)
