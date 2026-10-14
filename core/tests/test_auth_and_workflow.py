import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Dealer, Inventory, Order, OrderItem, OrderStatus, Product
from core.order_service import OrderService

User = get_user_model()


class DealerDistributorAuthAndWorkflowTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.api_client = APIClient()
        self.test_prefix = uuid.uuid4().hex[:6].upper()

        # Create two sample dealers
        self.dealer1 = Dealer.objects.create(
            dealer_code="DLR-001",
            name="Apex Motors",
            city="Pune",
            phone="9876543210",
            email="apex@example.com",
            gstin="27AABP5506A1Z6",
            credit_limit=Decimal("200000.00"),
        )
        self.dealer2 = Dealer.objects.create(
            dealer_code="DLR-002",
            name="Zenith Spares",
            city="Mumbai",
            phone="9876543211",
            email="zenith@example.com",
            gstin="27AABP5506A1Z7",
            credit_limit=Decimal("150000.00"),
        )

        # Setup user groups
        self.dealer_group, _ = Group.objects.get_or_create(name="Dealer")
        self.distributor_group, _ = Group.objects.get_or_create(name="Distributor")

        # Create Dealer 1 user
        self.user_d1 = User.objects.create_user(
            username="DLR-001",
            password="Dealer@001",
            email="apex@example.com",
        )
        self.user_d1.groups.add(self.dealer_group)
        self.dealer1.user = self.user_d1
        self.dealer1.save(update_fields=["user"])

        # Create Dealer 2 user
        self.user_d2 = User.objects.create_user(
            username="DLR-002",
            password="Dealer@002",
            email="zenith@example.com",
        )
        self.user_d2.groups.add(self.dealer_group)
        self.dealer2.user = self.user_d2
        self.dealer2.save(update_fields=["user"])

        # Create Distributor user
        self.distributor_user = User.objects.create_user(
            username="distributor",
            password="Distributor@123",
            email="distributor@vikmo.com",
            is_staff=True,
        )
        self.distributor_user.groups.add(self.distributor_group)

        # Create sample product with stock
        self.prod = Product.objects.create(
            sku=f"BRK-{self.test_prefix}",
            name="Ceramic Brake Pads",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="Pulsar 150",
            price=Decimal("1200.00"),
            description="Premium brake pad set",
        )
        self.inv = Inventory.objects.create(product=self.prod, quantity=50)

    # -------------------------------------------------------------
    # 1. Login & Authentication Tests
    # -------------------------------------------------------------
    def test_dealer_login_success(self):
        """Dealer logs in with correct credentials and is redirected to /dealer/dashboard/."""
        res = self.client.post("/dealer/login/", {
            "username": "DLR-001",
            "password": "Dealer@001",
        }, follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, "/dealer/dashboard/")

    def test_dealer_login_invalid_password(self):
        """Dealer login fails with wrong password."""
        res = self.client.post("/dealer/login/", {
            "username": "DLR-001",
            "password": "WrongPassword!",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Invalid dealer credentials")

    def test_distributor_login_success(self):
        """Distributor logs in with valid credentials and is redirected to /distributor/dashboard/."""
        res = self.client.post("/distributor/login/", {
            "username": "distributor",
            "password": "Distributor@123",
        }, follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, "/distributor/dashboard/")

    def test_distributor_login_invalid_credentials(self):
        """Distributor login fails with incorrect credentials."""
        res = self.client.post("/distributor/login/", {
            "username": "distributor",
            "password": "WrongPassword!",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Invalid distributor credentials")

    def test_dealer_cannot_login_as_distributor(self):
        """Attempting to use a Dealer account on the distributor login portal shows error."""
        res = self.client.post("/distributor/login/", {
            "username": "DLR-001",
            "password": "Dealer@001",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "This account is a Dealer account")

    def test_distributor_cannot_login_as_dealer(self):
        """Attempting to use a Distributor account on the dealer login portal shows error."""
        res = self.client.post("/dealer/login/", {
            "username": "distributor",
            "password": "Distributor@123",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "This account is a Distributor account")

    def test_login_page_renders_partnerdesk_ui_and_role_toggles(self):
        """Verifies login pages render 'VIKMO PartnerDesk', badge, segmented role toggle, and account note."""
        # Dealer Login Page
        res_dealer = self.client.get("/dealer/login/")
        self.assertEqual(res_dealer.status_code, 200)
        self.assertContains(res_dealer, "VIKMO PartnerDesk")
        self.assertContains(res_dealer, "Dealer & Distributor Portal")
        self.assertContains(res_dealer, 'id="tab-dealer"')
        self.assertContains(res_dealer, 'id="tab-distributor"')
        self.assertContains(res_dealer, 'id="toggle-pwd"')
        self.assertContains(res_dealer, "Authorized accounts only")

        # Distributor Login Page
        res_dist = self.client.get("/distributor/login/")
        self.assertEqual(res_dist.status_code, 200)
        self.assertContains(res_dist, "VIKMO PartnerDesk")
        self.assertContains(res_dist, "Dealer & Distributor Portal")
        self.assertContains(res_dist, 'id="tab-dealer"')
        self.assertContains(res_dist, 'id="tab-distributor"')
        self.assertContains(res_dist, 'id="toggle-pwd"')
        self.assertContains(res_dist, "Authorized accounts only")

    def test_dealer_logout(self):
        """Dealer logout clears session and redirects to /dealer/login/."""
        self.client.force_login(self.user_d1)
        res = self.client.get("/dealer/logout/", follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, "/dealer/login/")

    def test_distributor_logout(self):
        """Distributor logout clears session and redirects to /distributor/login/."""
        self.client.force_login(self.distributor_user)
        res = self.client.get("/distributor/logout/", follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, "/distributor/login/")

    # -------------------------------------------------------------
    # 2. Access Control & Dashboard RBAC Tests
    # -------------------------------------------------------------
    def test_unauthenticated_dealer_dashboard_redirects(self):
        """Unauthenticated user accessing /dealer/dashboard/ is redirected to /dealer/login/."""
        res = self.client.get("/dealer/dashboard/", follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/dealer/login/", res.url)

    def test_unauthenticated_distributor_dashboard_redirects(self):
        """Unauthenticated user accessing /distributor/dashboard/ is redirected to /distributor/login/."""
        res = self.client.get("/distributor/dashboard/", follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/distributor/login/", res.url)

    def test_dealer_cannot_access_distributor_dashboard(self):
        """Dealer user cannot access /distributor/dashboard/."""
        self.client.force_login(self.user_d1)
        res = self.client.get("/distributor/dashboard/", follow=False)
        self.assertIn(res.status_code, [302, 403])

    def test_distributor_cannot_access_dealer_dashboard(self):
        """Distributor user cannot access /dealer/dashboard/."""
        self.client.force_login(self.distributor_user)
        res = self.client.get("/dealer/dashboard/", follow=False)
        self.assertIn(res.status_code, [302, 403])

    # -------------------------------------------------------------
    # 3. Order Placement & Auto-binding Tests
    # -------------------------------------------------------------
    def test_dealer_order_creation_auto_binds_dealer_identity(self):
        """When an authenticated dealer places an order, dealer_id is automatically bound from user session."""
        self.api_client.force_authenticate(user=self.user_d1)
        # Even if request payload passes dealer_id = 999 or dealer2.id, it must bind to dealer1
        res = self.api_client.post("/api/orders/", {
            "dealer_id": self.dealer2.id,
            "items": [{"sku": self.prod.sku, "quantity": 2}],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(data["dealer_id"], self.dealer1.id)
        self.assertEqual(data["dealer_code"], "DLR-001")
        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(data["status_label"], "Pending")

    def test_dealer_orders_list_filtered_to_own_orders(self):
        """Authenticated dealer only sees their own orders in GET /api/orders/."""
        # Create an order for dealer1
        o1 = OrderService.create_order(dealer_id=self.dealer1.id, items_data=[{"sku": self.prod.sku, "quantity": 1}])[0]
        # Create an order for dealer2
        o2 = OrderService.create_order(dealer_id=self.dealer2.id, items_data=[{"sku": self.prod.sku, "quantity": 1}])[0]

        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.get("/api/orders/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        order_numbers = [item["order_number"] for item in res.json()["results"]]
        self.assertIn(o1.order_number, order_numbers)
        self.assertNotIn(o2.order_number, order_numbers)

    # -------------------------------------------------------------
    # 4. Cross-Dealer Isolation Tests
    # -------------------------------------------------------------
    def test_dealer_cannot_view_another_dealers_order(self):
        """Dealer 1 cannot view Dealer 2's order via GET /api/orders/<order_number>/."""
        o2 = OrderService.create_order(dealer_id=self.dealer2.id, items_data=[{"sku": self.prod.sku, "quantity": 1}])[0]

        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.get(f"/api/orders/{o2.order_number}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_dealer_cannot_modify_another_dealers_order(self):
        """Dealer 1 cannot edit Dealer 2's order via PUT /api/orders/<order_number>/."""
        o2 = OrderService.create_order(dealer_id=self.dealer2.id, items_data=[{"sku": self.prod.sku, "quantity": 1}])[0]

        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.put(f"/api/orders/{o2.order_number}/", {
            "items": [{"sku": self.prod.sku, "quantity": 5}]
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_dealer_cannot_cancel_another_dealers_order(self):
        """Dealer 1 cannot cancel Dealer 2's order via POST /api/orders/<order_number>/cancel/."""
        o2 = OrderService.create_order(dealer_id=self.dealer2.id, items_data=[{"sku": self.prod.sku, "quantity": 1}])[0]

        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.post(f"/api/orders/{o2.order_number}/cancel/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------
    # 5. Order Approval Workflow & Security Tests
    # -------------------------------------------------------------
    def test_anonymous_order_confirmation_rejected_401(self):
        """Unauthenticated requests attempting to confirm orders receive 401 Unauthorized."""
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 1}],
        )
        # Test standard confirmation route
        res1 = self.api_client.post(f"/api/orders/{order.order_number}/confirm/")
        self.assertEqual(res1.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res1.json()["error"]["code"], "UNAUTHORIZED")

        # Test distributor confirmation route
        res2 = self.api_client.post(f"/api/distributor/orders/{order.order_number}/confirm/")
        self.assertEqual(res2.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res2.json()["error"]["code"], "UNAUTHORIZED")

        # Verify order remains in DRAFT
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DRAFT)

    def test_dealer_cannot_confirm_order_403(self):
        """A dealer attempting to confirm an order receives 403 Forbidden."""
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 2}],
        )
        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.post(f"/api/orders/{order.order_number}/confirm/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.json()["error"]["code"], "FORBIDDEN")
        self.assertIn("Dealers are not authorized to confirm orders", res.json()["error"]["message"])

        # Verify order remains in DRAFT
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DRAFT)

    def test_authenticated_non_distributor_cannot_confirm_order_403(self):
        """Ordinary authenticated user without Distributor role receives 403 Forbidden."""
        plain_user = User.objects.create_user(username="regular_employee", password="SomePassword123")
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 1}],
        )
        self.api_client.force_authenticate(user=plain_user)
        res = self.api_client.post(f"/api/orders/{order.order_number}/confirm/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.json()["error"]["code"], "FORBIDDEN")

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DRAFT)

    def test_distributor_confirms_order_atomically_deducts_stock(self):
        """Distributor confirms a pending order: status transitions to CONFIRMED, inventory is decremented, confirmed_by recorded."""
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 5}],
        )
        initial_stock = self.inv.quantity  # 50

        self.api_client.force_authenticate(user=self.distributor_user)
        res = self.api_client.post(f"/api/distributor/orders/{order.order_number}/confirm/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["status"], "CONFIRMED")
        self.assertEqual(data["status_label"], "Confirmed")

        # Verify database changes
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        self.assertEqual(order.confirmed_by, self.distributor_user)
        self.assertIsNotNone(order.confirmed_at)

        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock - 5)

    def test_repeated_order_confirmation_rejected_safely(self):
        """Confirming an already confirmed order fails with 409 INVALID_TRANSITION and does not decrement stock twice."""
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 3}],
        )
        initial_stock = self.inv.quantity

        self.api_client.force_authenticate(user=self.distributor_user)
        res1 = self.api_client.post(f"/api/orders/{order.order_number}/confirm/")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)

        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock - 3)

        # Second confirmation must be safely rejected
        res2 = self.api_client.post(f"/api/orders/{order.order_number}/confirm/")
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res2.json()["error"]["code"], "INVALID_TRANSITION")

        # Verify stock was NOT decremented again
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock - 3)

    def test_direct_api_calls_cannot_bypass_role_permissions(self):
        """Passing fake role headers or spoofed IDs cannot bypass authorization."""
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 1}],
        )
        # Attempt confirmation with spoofed headers while anonymous
        res = self.api_client.post(
            f"/api/orders/{order.order_number}/confirm/",
            HTTP_X_ROLE="distributor",
            HTTP_X_USER_ID="1",
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_distributor_pending_orders_list(self):
        """Distributor pending orders endpoint lists only DRAFT orders across all dealers."""
        o1, _ = OrderService.create_order(dealer_id=self.dealer1.id, items_data=[{"sku": self.prod.sku, "quantity": 1}])
        o2, _ = OrderService.create_order(dealer_id=self.dealer2.id, items_data=[{"sku": self.prod.sku, "quantity": 2}])

        # Confirm o1
        OrderService.confirm_order(o1.order_number, confirmed_by_user=self.distributor_user)

        self.api_client.force_authenticate(user=self.distributor_user)
        res = self.api_client.get("/api/distributor/orders/pending/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        pending_numbers = [item["order_number"] for item in data["results"]]
        self.assertNotIn(o1.order_number, pending_numbers)
        self.assertIn(o2.order_number, pending_numbers)

    def test_dealer_cannot_access_distributor_pending_orders(self):
        """Dealer user attempting to access /api/distributor/orders/pending/ receives 403 Forbidden."""
        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.get("/api/distributor/orders/pending/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    # -------------------------------------------------------------
    # 6. Management Command Idempotency
    # -------------------------------------------------------------
    def test_setup_dealer_accounts_command_idempotent(self):
        """Calling setup_dealer_accounts twice runs cleanly and preserves linkages."""
        call_command("setup_dealer_accounts")
        call_command("setup_dealer_accounts")
        self.user_d1.refresh_from_db()
        self.assertTrue(self.user_d1.check_password("Dealer@001"))

    def test_create_distributor_command_idempotent_preserves_password(self):
        """Calling create_distributor without --reset-password preserves existing credentials."""
        call_command("create_distributor", username="distributor")
        self.distributor_user.refresh_from_db()
        self.assertTrue(self.distributor_user.check_password("Distributor@123"))

    # -------------------------------------------------------------
    # 7. Dealer Authorization, Anti-Tampering & Lifecycle Hardening
    # -------------------------------------------------------------
    def test_inactive_dealer_cannot_create_order(self):
        """Inactive dealers cannot place orders via API or OrderService."""
        self.dealer1.is_active = False
        self.dealer1.save(update_fields=["is_active"])

        # Service level
        with self.assertRaises(Exception) as ctx_err:
            OrderService.create_order(
                dealer_id=self.dealer1.id,
                items_data=[{"sku": self.prod.sku, "quantity": 1}],
            )
        self.assertIn("inactive", str(ctx_err.exception).lower())

        # API level authenticated
        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.post("/api/orders/", {
            "items": [{"sku": self.prod.sku, "quantity": 1}],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_dealer_cannot_spoof_another_dealer_id(self):
        """An authenticated dealer attempting to pass another dealer's ID has their own dealer identity bound."""
        self.api_client.force_authenticate(user=self.user_d1)
        res = self.api_client.post("/api/orders/", {
            "dealer_id": self.dealer2.id,
            "items": [{"sku": self.prod.sku, "quantity": 1}],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.json()["dealer_id"], self.dealer1.id)
        self.assertNotEqual(res.json()["dealer_id"], self.dealer2.id)

    def test_nonexistent_dealer_cannot_create_order(self):
        """Non-existent dealer ID (e.g. purged test dealer 595) is rejected with VALIDATION_ERROR."""
        res = self.api_client.post("/api/orders/", {
            "dealer_id": 999999,
            "items": [{"sku": self.prod.sku, "quantity": 1}],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

    def test_draft_order_does_not_deduct_inventory(self):
        """Creating draft orders never deducts inventory stock."""
        initial_stock = self.inv.quantity
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 5}],
        )
        self.assertEqual(order.status, OrderStatus.DRAFT)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock)

    def test_order_cancellation_restores_inventory_exactly_once(self):
        """Confirming an order deducts inventory once; cancelling it restores stock once."""
        initial_stock = self.inv.quantity
        order, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 5}],
        )
        # Confirm order
        OrderService.confirm_order(order.order_number, confirmed_by_user=self.distributor_user)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock - 5)

        # Cancel order
        OrderService.cancel_order(order.order_number)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock)

        # Attempting second cancel must fail
        with self.assertRaises(Exception):
            OrderService.cancel_order(order.order_number)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.quantity, initial_stock)

    def test_order_delete_draft_and_cancelled_only(self):
        """Only DRAFT and CANCELLED orders can be deleted via DELETE /api/orders/{order_number}/."""
        # 1. Draft order can be deleted
        o_draft, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 2}],
        )
        res_del = self.api_client.delete(f"/api/orders/{o_draft.order_number}/")
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Order.objects.filter(order_number=o_draft.order_number).exists())

        # 2. Confirmed order cannot be deleted directly
        o_conf, _ = OrderService.create_order(
            dealer_id=self.dealer1.id,
            items_data=[{"sku": self.prod.sku, "quantity": 2}],
        )
        OrderService.confirm_order(o_conf.order_number, confirmed_by_user=self.distributor_user)
        res_del_conf = self.api_client.delete(f"/api/orders/{o_conf.order_number}/")
        self.assertEqual(res_del_conf.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_del_conf.json()["error"]["code"], "INVALID_TRANSITION")

        # 3. Cancelled order can be deleted
        OrderService.cancel_order(o_conf.order_number)
        res_del_canc = self.api_client.delete(f"/api/orders/{o_conf.order_number}/")
        self.assertEqual(res_del_canc.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Order.objects.filter(order_number=o_conf.order_number).exists())

    def test_authoritative_seeded_dealer_protected_from_deletion(self):
        """Authoritative seeded dealers (DLR-001) cannot be deleted via DELETE /api/dealers/{id}/."""
        res = self.api_client.delete(f"/api/dealers/{self.dealer1.id}/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Dealer.objects.filter(id=self.dealer1.id).exists())

    def test_temporary_dealer_can_be_deleted(self):
        """Temporary test dealer created without orders can be cleanly deleted."""
        temp_dealer = Dealer.objects.create(
            dealer_code="TEMP-XYZ999",
            name="Temporary Test Dealer",
        )
        res = self.api_client.delete(f"/api/dealers/{temp_dealer.id}/")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Dealer.objects.filter(id=temp_dealer.id).exists())

    def test_reset_dev_database_command_dry_run(self):
        """Management command reset_dev_database --dry-run runs cleanly without error."""
        call_command("reset_dev_database", dry_run=True)


