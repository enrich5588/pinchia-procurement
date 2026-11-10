import time
from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .auth_views import FLOW_KEY
from .microsoft import (
    MicrosoftLoginError, build_client, configuration_problem,
    read_graph_profile, synchronize_user, validate_id_token,
)
from .models import Department, MicrosoftIdentity, UserProfile

TENANT = "11111111-1111-4111-8111-111111111111"
OBJECT = "22222222-2222-4222-8222-222222222222"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
SETTINGS = dict(
    M365_TENANT_ID=TENANT, M365_CLIENT_ID=CLIENT_ID,
    M365_CLIENT_SECRET="test-client-secret", M365_CERT_PRIVATE_KEY_PATH="",
    M365_CERT_THUMBPRINT="", M365_REDIRECT_URI="https://testserver/accounts/microsoft/callback/",
    M365_ALLOW_GUESTS=False, ALLOW_LOCAL_LOGIN=False,
    AUTHENTICATION_BACKENDS=["organization.backends.MicrosoftBackend"],
)


def claims(**changes):
    return {"tid": TENANT, "oid": OBJECT, **changes}


def profile(**changes):
    return {"id": OBJECT, "userPrincipalName": "staff@company.example", "mail": "staff@company.example",
            "displayName": "測試同仁", "department": "資訊部", "userType": "Member", **changes}


@override_settings(**SETTINGS)
class MicrosoftFlowTests(TestCase):
    def setUp(self):
        self.sdk_patch = patch("organization.auth_views.build_client")
        self.sdk = self.sdk_patch.start().return_value
        self.addCleanup(self.sdk_patch.stop)
        self.sdk.initiate_auth_code_flow.return_value = {
            "auth_uri": "https://login.microsoftonline.com/test-authorize?nonce=sent-nonce", "state": "test-state",
            "nonce": "test-nonce", "code_verifier": "test-verifier",
        }
        self.sdk.acquire_token_by_auth_code_flow.return_value = {
            "access_token": "sensitive-access-token", "id_token": "signed-token", "id_token_claims": claims(),
        }
        self.validation_patch = patch("organization.auth_views.validate_id_token", return_value=claims())
        self.validation = self.validation_patch.start()
        self.addCleanup(self.validation_patch.stop)
        self.graph_patch = patch("organization.auth_views.read_graph_profile", return_value=profile())
        self.graph = self.graph_patch.start()
        self.addCleanup(self.graph_patch.stop)

    def start(self, next_url="/supplies/"):
        return self.client.post(reverse("microsoft_login"), {"next": next_url}, secure=True)

    def callback(self, **parameters):
        return self.client.get(reverse("microsoft_callback"), {"code": "test-code", "state": "test-state", **parameters})

    def test_login_page_is_microsoft_only(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "使用公司 M365 帳號登入")
        self.assertNotContains(response, 'name="password"')
        self.assertNotContains(response, "test-client-secret")
        self.assertEqual(self.client.post(reverse("login"), {}).status_code, 405)

    @override_settings(M365_CLIENT_ID="")
    def test_unconfigured_page_has_clear_status_and_no_password_fallback(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "尚未完成設定")
        self.assertContains(response, "disabled")
        self.assertNotContains(response, 'name="password"')

    def test_start_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(reverse("microsoft_login")).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("microsoft_login")).status_code, 403)
        self.sdk.initiate_auth_code_flow.assert_not_called()

    def test_wrong_origin_redirects_before_creating_session_flow(self):
        response = self.client.post(reverse("microsoft_login"), {"next": "/assets/"})
        self.assertEqual(response.url, "https://testserver/accounts/login/?next=%2Fassets%2F")
        self.assertNotIn(FLOW_KEY, self.client.session)
        self.sdk.initiate_auth_code_flow.assert_not_called()

    @override_settings(M365_CLIENT_ID="")
    def test_unconfigured_start_has_explicit_error_without_network(self):
        response = self.client.post(reverse("microsoft_login"), follow=True)
        self.assertContains(response, "尚未完成設定")
        self.sdk.initiate_auth_code_flow.assert_not_called()

    def test_start_stores_flow_server_side_and_requests_only_user_read(self):
        old_session = self.client.session.session_key
        response = self.start()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://login.microsoftonline.com/"))
        self.assertNotEqual(old_session, self.client.session.session_key)
        self.assertEqual(self.client.session[FLOW_KEY]["next"], "/supplies/")
        self.sdk.initiate_auth_code_flow.assert_called_once_with(
            scopes=["User.Read"], redirect_uri=SETTINGS["M365_REDIRECT_URI"],
            response_mode="query", prompt="select_account",
        )

    def test_success_creates_unprivileged_user_and_syncs_graph_department(self):
        self.start()
        response = self.callback()
        self.assertRedirects(response, "/supplies/")
        identity = MicrosoftIdentity.objects.get()
        self.assertEqual(identity.user.profile.department.name, "資訊部")
        self.assertEqual(identity.user.first_name, "測試同仁")
        self.assertFalse(identity.user.is_staff)
        self.assertFalse(identity.user.is_superuser)
        self.assertFalse(identity.user.has_usable_password())
        self.assertIsNotNone(identity.last_synced_at)
        self.assertEqual(int(self.client.session["_auth_user_id"]), identity.user_id)
        self.assertNotIn(FLOW_KEY, self.client.session)
        self.assertNotIn("sensitive-access-token", str(dict(self.client.session)))
        self.sdk.acquire_token_by_auth_code_flow.assert_called_once()
        self.validation.assert_called_once_with("signed-token", "sent-nonce")
        self.assertEqual(self.client.session.get_expiry_age(), 8 * 60 * 60)

    def test_external_next_is_rejected_at_both_start_and_callback(self):
        for external in ["https://evil.example/", "//evil.example/", "https://testserver@evil.example/"]:
            with self.subTest(url=external):
                self.start(external)
                self.assertEqual(self.client.session[FLOW_KEY]["next"], "/")
        saved = self.client.session
        saved[FLOW_KEY]["next"] = "https://evil.example/"
        saved.save()
        response = self.callback()
        self.assertEqual(response.url, "/")

    def test_missing_expired_and_wrong_state_flows_do_not_exchange_tokens(self):
        self.assertRedirects(self.callback(), reverse("login"))
        self.start()
        self.assertRedirects(self.callback(state="wrong"), reverse("login"))
        self.assertNotIn(FLOW_KEY, self.client.session)
        self.start()
        session = self.client.session
        session[FLOW_KEY]["created_at"] = time.time() - 601
        session.save()
        self.assertRedirects(self.callback(), reverse("login"))
        self.sdk.acquire_token_by_auth_code_flow.assert_not_called()

    def test_callback_replay_is_rejected(self):
        self.start()
        self.callback()
        self.assertRedirects(self.callback(), reverse("login"))
        self.assertEqual(self.sdk.acquire_token_by_auth_code_flow.call_count, 1)

    def test_msal_nonce_or_token_validation_failure_does_not_log_in(self):
        self.start()
        self.sdk.acquire_token_by_auth_code_flow.side_effect = RuntimeError("nonce mismatch")
        self.assertRedirects(self.callback(), reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.graph.assert_not_called()

    def test_consent_denial_does_not_expose_provider_details(self):
        self.start()
        self.sdk.acquire_token_by_auth_code_flow.return_value = {
            "error": "access_denied", "error_description": "sensitive-provider-detail",
        }
        response = self.client.get(reverse("microsoft_callback"),
                                   {"error": "access_denied", "state": "test-state"}, follow=True)
        self.assertContains(response, "授權遭拒")
        self.assertNotContains(response, "sensitive-provider-detail")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_tenant_is_rejected_before_graph_call(self):
        self.start()
        self.validation.return_value = claims(tid=str(uuid4()))
        self.assertRedirects(self.callback(), reverse("login"))
        self.graph.assert_not_called()

    def test_invalid_signed_token_is_rejected_before_graph_or_login(self):
        self.start()
        self.validation.side_effect = MicrosoftLoginError("憑證驗證失敗")
        self.assertRedirects(self.callback(), reverse("login"))
        self.graph.assert_not_called()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_graph_failure_is_recoverable_and_does_not_create_account(self):
        self.start()
        self.graph.side_effect = MicrosoftLoginError("Graph 暫時無法連線")
        response = self.client.get(reverse("microsoft_callback"),
                                   {"code": "test-code", "state": "test-state"}, follow=True)
        self.assertContains(response, "Graph 暫時無法連線")
        self.assertFalse(MicrosoftIdentity.objects.exists())

    def test_password_authentication_and_admin_password_endpoint_are_disabled(self):
        get_user_model().objects.create_superuser("local-admin", password="password")
        self.assertIsNone(authenticate(username="local-admin", password="password"))
        for method in [self.client.get, self.client.post]:
            response = method(reverse("admin:login"), {"username": "local-admin", "password": "password"})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("login")))
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(ALLOW_LOCAL_LOGIN=True, AUTHENTICATION_BACKENDS=[
        "organization.backends.MicrosoftBackend", "django.contrib.auth.backends.ModelBackend",
    ])
    def test_local_login_requires_explicit_enablement(self):
        user = get_user_model().objects.create_user("local-dev", password="password")
        response = self.client.get(reverse("login"))
        self.assertContains(response, "本機登入")
        self.assertContains(response, 'name="password"')
        self.assertEqual(self.client.post(reverse("login"), {
            "username": user.username, "password": "password",
        }).status_code, 302)


@override_settings(**SETTINGS)
class MicrosoftIdentityTests(TestCase):
    def test_repeat_login_updates_department_without_changing_user_or_identity(self):
        user = synchronize_user(claims(), profile())
        second = synchronize_user(claims(), profile(department="都更事業部", userPrincipalName="new@company.example"))
        self.assertEqual(user.pk, second.pk)
        user.refresh_from_db()
        self.assertEqual(user.profile.department.name, "都更事業部")
        self.assertEqual(user.microsoft_identity.principal_name, "new@company.example")
        self.assertEqual(MicrosoftIdentity.objects.count(), 1)

    def test_empty_department_guests_or_mismatched_ids_never_create_users(self):
        for changes in [{"department": None}, {"department": "  "}, {"department": "x" * 65},
                        {"userType": "Guest"}, {"userType": None}, {"id": str(uuid4())}]:
            with self.subTest(changes=changes):
                with self.assertRaises(MicrosoftLoginError):
                    synchronize_user(claims(), profile(**changes))
                self.assertFalse(get_user_model().objects.exists())
                self.assertFalse(Department.objects.exists())

    def test_matching_email_or_username_does_not_take_over_existing_account(self):
        existing = get_user_model().objects.create_superuser(
            "staff@company.example", email="staff@company.example", password="existing",
        )
        new = synchronize_user(claims(), profile())
        self.assertNotEqual(existing.pk, new.pk)
        self.assertFalse(new.is_superuser)
        self.assertFalse(hasattr(existing, "microsoft_identity"))
        self.assertTrue(existing.check_password("existing"))

    def test_explicit_binding_preserves_historical_user_and_privileges(self):
        existing = get_user_model().objects.create_user("wang", is_staff=True)
        call_command("link_m365_identity", username="wang", object_id=OBJECT,
                     tenant_id=TENANT, stdout=StringIO())
        user = synchronize_user(claims(), profile())
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.username, "wang")
        self.assertTrue(user.is_staff)

    def test_disabled_account_cannot_log_in_or_change_department(self):
        user = synchronize_user(claims(), profile())
        user.is_active = False
        user.save()
        with self.assertRaises(MicrosoftLoginError):
            synchronize_user(claims(), profile(department="管理部"))
        self.assertEqual(user.profile.department.name, "資訊部")

    def test_identity_binding_is_unique_and_cannot_silently_move(self):
        first = get_user_model().objects.create_user("first")
        second = get_user_model().objects.create_user("second")
        options = dict(object_id=OBJECT, tenant_id=TENANT, stdout=StringIO())
        call_command("link_m365_identity", username="first", **options)
        call_command("link_m365_identity", username="first", **options)
        with self.assertRaises(CommandError):
            call_command("link_m365_identity", username="second", **options)
        with self.assertRaises(CommandError):
            call_command("link_m365_identity", username="first", object_id=str(uuid4()),
                         tenant_id=TENANT, stdout=StringIO())
        with self.assertRaises(IntegrityError), transaction.atomic():
            MicrosoftIdentity.objects.create(user=second, tenant_id=TENANT, object_id=OBJECT)
        self.assertEqual(MicrosoftIdentity.objects.get().user_id, first.pk)


@override_settings(**SETTINGS)
class MicrosoftServiceTests(TestCase):
    def test_configuration_rejects_invalid_or_insecure_urls(self):
        for uri in ["http://company.example/accounts/microsoft/callback/", "https://testserver/wrong/",
                    "https://testserver/accounts/microsoft/callback/?next=evil", "https://[bad"]:
            with self.subTest(uri=uri), override_settings(M365_REDIRECT_URI=uri):
                self.assertTrue(configuration_problem())
        with override_settings(DEBUG=True, M365_REDIRECT_URI="http://localhost:8000/accounts/microsoft/callback/"):
            self.assertFalse(configuration_problem())
        with override_settings(DEBUG=False, M365_REDIRECT_URI="http://localhost:8000/accounts/microsoft/callback/"):
            self.assertTrue(configuration_problem())

    def test_configuration_requires_exactly_one_credential_and_server_side_session(self):
        self.assertFalse(configuration_problem())
        for changes in [dict(M365_CLIENT_SECRET=""), dict(M365_CLIENT_ID="invalid"),
                        dict(M365_CERT_PRIVATE_KEY_PATH="key.pem"),
                        dict(M365_CERT_PRIVATE_KEY_PATH="key.pem", M365_CERT_THUMBPRINT="thumb"),
                        dict(SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies")]:
            with self.subTest(changes=changes), override_settings(**changes):
                self.assertTrue(configuration_problem())

    @patch("organization.microsoft.msal.ConfidentialClientApplication")
    def test_msal_client_uses_fixed_tenant_timeouts_and_no_refresh_token_scope(self, client):
        build_client()
        arguments = client.call_args.kwargs
        self.assertEqual(arguments["authority"], f"https://login.microsoftonline.com/{TENANT}")
        self.assertEqual(arguments["exclude_scopes"], ["offline_access"])
        self.assertEqual(arguments["timeout"], (5, 15))

    @patch("organization.microsoft.msal.ConfidentialClientApplication")
    def test_certificate_credential_is_loaded_only_on_server(self, client):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "key.pem"
            path.write_text("test-private-key", encoding="utf-8")
            with override_settings(M365_CLIENT_SECRET="", M365_CERT_PRIVATE_KEY_PATH=str(path),
                                   M365_CERT_THUMBPRINT="thumb"):
                build_client()
        self.assertEqual(client.call_args.kwargs["client_credential"], {
            "private_key": "test-private-key", "thumbprint": "thumb",
        })

    @patch("organization.microsoft.requests.get")
    def test_graph_requests_department_explicitly_with_timeout_and_no_redirects(self, get):
        get.return_value = Mock(status_code=200)
        get.return_value.json.return_value = profile()
        self.assertEqual(read_graph_profile("token")["department"], "資訊部")
        self.assertIn("department", get.call_args.kwargs["params"]["$select"])
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 15))
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("organization.microsoft.requests.get")
    def test_graph_errors_invalid_json_and_network_failure_are_explicit(self, get):
        for response in [Mock(status_code=403), Mock(status_code=302), Mock(status_code=429)]:
            get.return_value = response
            with self.assertRaises(MicrosoftLoginError):
                read_graph_profile("token")
        get.return_value = Mock(status_code=200)
        get.return_value.json.side_effect = ValueError("invalid JSON")
        with self.assertRaises(MicrosoftLoginError):
            read_graph_profile("token")
        get.side_effect = requests.Timeout("secret-detail")
        with self.assertRaisesRegex(MicrosoftLoginError, "暫時無法連線"):
            read_graph_profile("token")


@override_settings(**SETTINGS)
class SignedTokenTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.keys_patch = patch("organization.microsoft.signing_keys")
        self.keys = self.keys_patch.start().return_value
        self.addCleanup(self.keys_patch.stop)
        self.keys.get_signing_key_from_jwt.return_value.key = self.key.public_key()

    def token(self, changes=None, key=None):
        now = int(time.time())
        payload = {
            **claims(), "sub": "subject", "aud": CLIENT_ID,
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "iat": now, "nbf": now - 1, "exp": now + 300, "nonce": "sent-nonce",
            **(changes or {}),
        }
        return jwt.encode(payload, key or self.key, algorithm="RS256", headers={"kid": "test-key"})

    def test_valid_rsa_signed_token_is_accepted(self):
        result = validate_id_token(self.token(), "sent-nonce")
        self.assertEqual(result["oid"], OBJECT)
        self.assertEqual(result["tid"], TENANT)

    def test_forged_signature_is_rejected(self):
        with self.assertRaises(MicrosoftLoginError):
            validate_id_token(self.token(key=self.other_key), "sent-nonce")

    def test_wrong_issuer_audience_expiry_future_or_nonce_are_rejected(self):
        for changes in [
            {"iss": "https://evil.example/"}, {"aud": str(uuid4())},
            {"aud": [CLIENT_ID, "other"]}, {"exp": int(time.time()) - 300},
            {"nbf": int(time.time()) + 300}, {"iat": int(time.time()) + 300},
            {"nonce": "wrong"}, {"nonce": None},
        ]:
            with self.subTest(changes=changes), self.assertRaises(MicrosoftLoginError):
                validate_id_token(self.token(changes), "sent-nonce")

    def test_unsigned_token_or_missing_required_claim_is_rejected(self):
        unsigned = jwt.encode(claims(), None, algorithm="none")
        with self.assertRaises(MicrosoftLoginError):
            validate_id_token(unsigned, "sent-nonce")
        token = self.token()
        payload = jwt.decode(token, options={"verify_signature": False})
        for name in ["sub", "exp", "aud", "iss", "iat", "oid", "tid", "nonce"]:
            incomplete = {key: value for key, value in payload.items() if key != name}
            signed = jwt.encode(incomplete, self.key, algorithm="RS256")
            with self.subTest(claim=name), self.assertRaises(MicrosoftLoginError):
                validate_id_token(signed, "sent-nonce")

    def test_signing_key_fetch_failure_is_not_a_login_bypass(self):
        self.keys.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("offline")
        with self.assertRaises(MicrosoftLoginError):
            validate_id_token(self.token(), "sent-nonce")

    def test_missing_nonce_or_token_never_fetches_signing_keys(self):
        for token, nonce in [(None, "sent-nonce"), (self.token(), "")]:
            with self.assertRaises(MicrosoftLoginError):
                validate_id_token(token, nonce)
        self.keys.get_signing_key_from_jwt.assert_not_called()
