from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from procurement.models import OfficeSupplyApplication
from .models import Department, FeaturePanel, PermissionAudit, PermissionRule, UserProfile
from .panel_views import save_panels
from .panels import PANEL_KEYS, panel_available
from .permission_service import revision_for
from .permissions import has_permission


class PanelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('panel-admin')
        self.user = User.objects.create_user('panel-user')
        self.manager = User.objects.create_user('panel-manager')
        self.department = Department.objects.create(name='管理與事業發展部')
        for user in [self.user, self.manager]:
            UserProfile.objects.create(user=user, department=self.department)
        self.url = reverse('panel_management')

    def values(self, **changes):
        return {**dict(FeaturePanel.objects.values_list('code', 'status')), **changes}

    def save(self, values, actor=None, revision=None):
        return save_panels(actor or self.admin, values,
                           revision if revision is not None else revision_for(self.values()))

    def test_existing_six_panels_remain_open_after_upgrade(self):
        self.assertEqual(set(FeaturePanel.objects.values_list('code', flat=True)), PANEL_KEYS)
        self.assertEqual(FeaturePanel.objects.filter(status='open').count(), 6)

    def test_developing_panels_block_all_six_module_get_and_post_routes(self):
        self.client.force_login(self.user)
        for code, route in [('supplies', 'supplies'), ('equipment', 'equipment_procurement'),
                            ('assets', 'asset_list'), ('registrations', 'registration_list'),
                            ('collaboration', 'collaboration_task_list'), ('approvals', 'approval_list')]:
            with self.subTest(code=code):
                self.save(self.values(**{code: 'developing'}))
                for method in [self.client.get, self.client.post]:
                    self.assertEqual(method(reverse(route)).status_code, 403)
                self.assertFalse(has_permission(self.user, code + '.access'))

    def test_explicit_personal_grant_and_management_department_cannot_bypass_panel(self):
        self.save(self.values(supplies='ready'))
        PermissionRule.objects.create(user=self.manager, permission='supplies.access', effect='allow')
        PermissionRule.objects.create(user=self.manager, permission='supplies.manage', effect='allow')
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('supplies')).status_code, 403)
        self.assertFalse(has_permission(self.manager, 'supplies.manage'))

    def test_superuser_can_test_closed_modules_and_manage_panels(self):
        self.save({code: 'developing' for code in PANEL_KEYS})
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        for route in ['supplies', 'equipment_procurement', 'asset_list', 'registration_list',
                      'collaboration_task_list', 'approval_list']:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)

    def test_home_hides_closed_module_links_counts_and_activity(self):
        application = OfficeSupplyApplication.objects.create(
            case_no='261111951', department=self.department, applicant=self.user,
            need_date=date(2026, 11, 20), created_by=self.user, updated_by=self.user)
        self.save(self.values(supplies='developing'))
        self.client.force_login(self.user)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, application.case_no)
        self.assertNotContains(response, 'href="/supplies/"')
        self.assertNotContains(response, 'href="/supplies/new/"')
        self.assertEqual(response.context['supply_pending'], 0)

    def test_reopen_takes_effect_without_new_login_and_retains_personal_restriction(self):
        self.client.force_login(self.user)
        self.save(self.values(assets='ready'))
        self.assertEqual(self.client.get(reverse('asset_list')).status_code, 403)
        self.save(self.values(assets='open'))
        self.assertEqual(self.client.get(reverse('asset_list')).status_code, 200)
        PermissionRule.objects.create(user=self.user, permission='assets.access', effect='deny')
        self.assertEqual(self.client.get(reverse('asset_list')).status_code, 403)

    def test_anonymous_and_non_superuser_cannot_manage_in_view_or_service(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for user in [self.user, self.manager]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                self.save(self.values(supplies='ready'), actor=user)

    def test_get_is_read_only_and_post_requires_csrf(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), '面板管理')
        self.assertFalse(PermissionAudit.objects.exists())
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, {}).status_code, 403)

    def test_save_records_changes_and_noop_does_not_add_audit(self):
        self.assertEqual(self.save(self.values(supplies='ready')), 1)
        audit = PermissionAudit.objects.get(target_type='panel')
        self.assertEqual(audit.changes, {'status': {'before': 'open', 'after': 'ready'}})
        self.assertEqual(self.save(self.values()), 0)
        self.assertEqual(PermissionAudit.objects.count(), 1)

    def test_stale_missing_and_invalid_settings_never_overwrite(self):
        old = revision_for(self.values())
        self.save(self.values(assets='developing'))
        for values, revision in [(self.values(supplies='ready'), old),
                                 ({'supplies': 'ready'}, revision_for(self.values())),
                                 (self.values(supplies='invalid'), revision_for(self.values()))]:
            with self.assertRaises(ValidationError):
                self.save(values, revision=revision)
        self.assertEqual(FeaturePanel.objects.get(code='supplies').status, 'open')

    def test_post_redirect_and_stale_page_reports_conflict(self):
        self.client.force_login(self.admin)
        data = self.values(supplies='ready')
        data['revision'] = revision_for(self.values())
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        data.pop('supplies')
        self.assertEqual(self.client.post(self.url, data).status_code, 422)

    @override_settings(FEATURE_OPEN_TO_ALL=False)
    def test_global_gate_still_overrides_open_panel_for_regular_users(self):
        self.assertFalse(panel_available(self.user, 'supplies'))
        self.assertTrue(panel_available(self.admin, 'supplies'))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), '全站功能開關')

    def test_missing_panel_fails_closed_without_implicit_creation(self):
        FeaturePanel.objects.filter(code='assets').delete()
        self.assertFalse(has_permission(self.user, 'assets.access'))
        self.assertFalse(FeaturePanel.objects.filter(code='assets').exists())
