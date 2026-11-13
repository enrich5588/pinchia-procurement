import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, AnonymousUser
from django.contrib.auth.signals import user_login_failed
from django.core.management import call_command
from django.db import transaction
from django.http import HttpResponse
from django.test import TestCase, override_settings, RequestFactory
from django.urls import path, reverse
from django.utils import timezone

from .audit import audit_context
from .models import Department, FeaturePanel, OperationLog, PermissionAudit


def edit_department(request):
    department = Department.objects.get(pk=request.POST['id'])
    department.name = request.POST['name']
    department.save(update_fields=['name'])
    if request.POST.get('fail'):
        raise RuntimeError('Intentional test rollback')
    return HttpResponse('ok')


urlpatterns = [path('audit-test/', edit_department)]


class OperationAuditTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('audit-admin')
        self.staff = User.objects.create_user('audit-staff')
        self.department = Department.objects.create(name='紀錄測試部門')
        OperationLog.objects.all().delete()

    @override_settings(ROOT_URLCONF=__name__)
    def test_request_records_actor_exact_changes_without_query_or_body_secrets(self):
        self.client.force_login(self.admin)
        response = self.client.post('/audit-test/?access_token=never-log-this', {
            'id': self.department.pk, 'name': '新的部門名稱', 'password': 'password-secret'})
        self.assertEqual(response.status_code, 200)
        log = OperationLog.objects.get(action='update', model_label='platform_stub.department')
        self.assertEqual(log.actor_id, self.admin.pk)
        self.assertEqual(log.changes['name'], {'before': '紀錄測試部門', 'after': '新的部門名稱'})
        self.assertTrue(OperationLog.objects.filter(action='request', request_id=log.request_id, status_code=200).exists())
        payload = json.dumps(list(OperationLog.objects.values()), default=str)
        self.assertNotIn('password-secret', payload)
        self.assertNotIn('never-log-this', payload)

    @override_settings(ROOT_URLCONF=__name__)
    def test_failed_request_rolls_back_data_and_mutation_log_but_records_failure(self):
        self.client.force_login(self.admin)
        self.client.raise_request_exception = False
        response = self.client.post('/audit-test/', {'id': self.department.pk, 'name': '不應儲存', 'fail': '1'})
        self.assertEqual(response.status_code, 500)
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, '紀錄測試部門')
        self.assertFalse(OperationLog.objects.filter(action='update').exists())
        self.assertTrue(OperationLog.objects.filter(action='request', status_code=500).exists())

    def test_queryset_update_bulk_insert_bulk_update_and_delete_are_recorded(self):
        with audit_context(source='批次作業'):
            departments = Department.objects.bulk_create([Department(name='批次一'), Department(name='批次二')])
            self.assertEqual(OperationLog.objects.filter(action='create').count(), 2)
            Department.objects.filter(pk=departments[0].pk).update(name='批次改名')
            departments[1].name = '批次更新'
            Department.objects.bulk_update([departments[1]], ['name'])
            departments[0].delete()
        self.assertEqual(OperationLog.objects.filter(action='update').count(), 2)
        self.assertEqual(OperationLog.objects.filter(action='delete').count(), 1)
        self.assertEqual(set(OperationLog.objects.values_list('source', flat=True)), {'批次作業'})

    def test_atomic_rollback_removes_mutation_logs(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.department.name = '回滾測試'
                self.department.save()
                raise RuntimeError()
        self.assertFalse(OperationLog.objects.exists())

    def test_save_update_fields_never_claims_unsaved_changes(self):
        self.department.name = '不應修改'
        self.department.save(update_fields=[])
        self.assertFalse(OperationLog.objects.exists())

    def test_password_changes_are_marked_without_hashes(self):
        self.staff.set_password('never-store-plaintext')
        self.staff.save()
        log = OperationLog.objects.get(action='update')
        self.assertIn('password', log.changes)
        payload = json.dumps(log.changes)
        self.assertNotIn('never-store-plaintext', payload)
        self.assertNotIn(self.staff.password, payload)
        self.assertNotIn('pbkdf2', payload)

    def test_login_logout_and_failed_login_do_not_store_credentials(self):
        self.client.force_login(self.staff)
        self.client.logout()
        with audit_context(request=RequestFactory().post('/accounts/login/')):
            user_login_failed.send(sender=type(self), credentials={'password':'hidden-secret','token':'hidden-token'})
        self.assertTrue(OperationLog.objects.filter(action='login', actor=self.staff).exists())
        self.assertTrue(OperationLog.objects.filter(action='logout', actor=self.staff).exists())
        self.assertTrue(OperationLog.objects.filter(action='login_failed').exists())
        self.assertNotIn('hidden-secret', json.dumps(list(OperationLog.objects.values()), default=str))

    def test_many_to_many_group_changes_and_reverse_clear_are_audited(self):
        group = Group.objects.create(name='測試群組')
        OperationLog.objects.all().delete()
        self.staff.groups.add(group)
        group.user_set.clear()
        self.assertEqual(OperationLog.objects.filter(action='update').count(), 2)

    def test_context_is_not_reused_by_background_tasks(self):
        request = RequestFactory().get('/')
        request.user = self.admin
        with audit_context(request=request):
            self.department.name = '由管理員修改'
            self.department.save()
        self.department.name = '背景修改'
        self.department.save()
        self.assertIsNone(OperationLog.objects.first().actor_id)
        self.assertEqual(OperationLog.objects.last().actor_id, self.admin.pk)

    def test_audit_failure_prevents_successful_business_write(self):
        with patch('organization.audit.record', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.department.name = '不可無紀錄修改'
                self.department.save()
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, '紀錄測試部門')

    def test_logs_page_requires_superuser_and_does_not_render_html_changes(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('operation_logs')).status_code, 403)
        self.department.name = '<script>test</script>'
        self.department.save()
        self.client.force_login(self.admin)
        response = self.client.get(reverse('operation_logs'), {'action':'update','q':'<script>'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<script>test</script>')
        self.assertContains(response, '&lt;script&gt;test&lt;/script&gt;')

    def test_retention_removes_only_expired_logs_including_legacy_permission_history(self):
        from .management.commands.maintain_operation_logs import purge
        now = timezone.now()
        self.department.name = '舊紀錄'
        self.department.save()
        old = OperationLog.objects.get(action='update')
        cutoff = now - timedelta(days=30)
        OperationLog.objects.filter(pk=old.pk).update(created_at=cutoff-timedelta(seconds=1))
        boundary = OperationLog.objects.create(actor_label='邊界',action='request',source='測試',request_id=uuid4())
        OperationLog.objects.filter(pk=boundary.pk).update(created_at=cutoff)
        legacy = PermissionAudit.objects.create(actor=self.admin,actor_label='admin',target_type='panel',
                                                target_id=1,target_label='舊紀錄',changes={})
        PermissionAudit.objects.filter(pk=legacy.pk).update(created_at=cutoff-timedelta(seconds=1))
        with patch('organization.audit.timezone.now', return_value=now):
            purge()
        self.assertFalse(OperationLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(OperationLog.objects.filter(pk=boundary.pk).exists())
        self.assertFalse(PermissionAudit.objects.filter(pk=legacy.pk).exists())
        self.assertTrue(Department.objects.filter(pk=self.department.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.admin.pk).exists())

    def test_retention_is_read_only_until_explicit_cleanup_command(self):
        self.department.name = '過期紀錄'
        self.department.save()
        log = OperationLog.objects.get(action='update')
        OperationLog.objects.filter(pk=log.pk).update(created_at=timezone.now()-timedelta(days=31))
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse('operation_logs')), '過期紀錄')
        self.assertTrue(OperationLog.objects.filter(pk=log.pk).exists())
        call_command('maintain_operation_logs')
        self.assertFalse(OperationLog.objects.filter(pk=log.pk).exists())

    def test_verified_login_correlates_earlier_sync_changes_to_login_user(self):
        from .audit_middleware import OperationAuditMiddleware
        request = RequestFactory().get('/accounts/microsoft/callback/?code=secret-auth-code')
        request.user = AnonymousUser()
        def finish_login(request):
            self.department.name = '登入同步'
            self.department.save()
            request.user = self.staff
            return HttpResponse('ok')
        OperationAuditMiddleware(finish_login)(request)
        change = OperationLog.objects.get(action='update')
        self.assertEqual(change.actor_id, self.staff.pk)
        self.assertNotIn('secret-auth-code', json.dumps(list(OperationLog.objects.values()), default=str))

    def test_panel_log_uses_human_readable_label(self):
        panel = FeaturePanel.objects.get(code='supplies')
        panel.status = 'ready'
        panel.save(update_fields=['status'])
        self.assertEqual(OperationLog.objects.get(action='update').object_label, '辦公用品申請')

    def test_recent_legacy_permission_audit_is_backfilled_with_original_time(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        created = timezone.now()-timedelta(days=3)
        legacy = PermissionAudit.objects.create(actor=self.admin,actor_label='audit-admin',target_type='panel',
                    target_id=1,target_label='辦公用品申請',changes={'status':{'before':'open','after':'ready'}})
        PermissionAudit.objects.filter(pk=legacy.pk).update(created_at=created)
        migration = import_module('organization.migrations.0009_operationlog')
        migration.preserve_recent_permission_history(apps, SimpleNamespace(connection=connection))
        log = OperationLog.objects.get(source='既有權限／面板紀錄')
        self.assertEqual(log.created_at, created)
        self.assertEqual(log.actor_id, self.admin.pk)
        self.assertEqual(log.changes, legacy.changes)

    def test_group_deletion_preserves_members_removed_by_cascade(self):
        group = Group.objects.create(name='刪除前群組')
        self.staff.groups.add(group)
        OperationLog.objects.all().delete()
        group.delete()
        log = OperationLog.objects.get(action='delete', model_label='auth.group')
        self.assertEqual(log.changes['members']['before'], [self.staff.pk])
        self.assertIsNone(log.changes['members']['after'])
