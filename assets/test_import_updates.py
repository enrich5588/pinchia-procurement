from datetime import date
from django.test import override_settings
from django.urls import reverse
from organization.testing import OpenPanelsTestCase
from organization.models import OperationLog
from . import test_bulk_upload as fixtures
workbook_upload = fixtures.workbook_upload
from .models import Asset, AssetImage, AssetImportBatch


class AssetImportUpdateTests(OpenPanelsTestCase):
    setUp = fixtures.AssetBulkUploadTests.setUp
    client_for = fixtures.AssetBulkUploadTests.client_for
    valid_row = fixtures.AssetBulkUploadTests.valid_row
    upload_for_preview = fixtures.AssetBulkUploadTests.upload_for_preview
    preview_post_data = fixtures.AssetBulkUploadTests.preview_post_data

    def existing(self, number='PCA-01-001'):
        return Asset.objects.create(asset_no=number, name='原有筆電', category='電腦設備',
            company=Asset.Company.PINJIA_DEVELOPMENT, department=self.it, custodian=self.staff,
            purchase_date=date(2024,1,1), created_by=self.staff, updated_by=self.staff, notes='原備註')

    def confirm(self, client, batch, **changes):
        data = self.preview_post_data(batch)
        data.update(changes)
        return client.post(reverse('asset_bulk_upload_preview', args=[batch.pk]), data)

    def test_number_key_updates_existing_in_place_preserving_creator_images_and_audit(self):
        asset = self.existing()
        image = AssetImage.objects.create(asset=asset, image='retained/original.png')
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client, [self.valid_row(' pca-01-001 ')], {'overwrite_existing':'on'})
        self.assertTrue(batch.overwrite_existing)
        self.assertEqual(batch.rows[0]['target_id'], asset.pk)
        self.assertContains(client.get(reverse('asset_bulk_upload_preview',args=[batch.pk])), '覆蓋更新')
        response = self.confirm(client, batch)
        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(Asset.objects.count(), 1)
        self.assertEqual(asset.name, '商務筆電')
        self.assertEqual(asset.notes, '')
        self.assertEqual(asset.created_by, self.staff)
        self.assertEqual(asset.updated_by, self.manager)
        self.assertTrue(AssetImage.objects.filter(pk=image.pk, asset=asset).exists())
        event = OperationLog.objects.filter(action='update', model_label='assets.asset',object_id=str(asset.pk)).first()
        self.assertEqual(event.actor_id, self.manager.pk)
        self.assertEqual(event.changes['name'], {'before':'原有筆電','after':'商務筆電'})

    def test_mixed_new_and_update_batch_reports_counts(self):
        self.existing()
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row(),self.valid_row('PCA-01-002')],{'overwrite_existing':'on'})
        response = self.confirm(client,batch)
        self.assertEqual(response.status_code,302)
        response = client.get(reverse('asset_list'))
        self.assertContains(response,'新增 1 筆財產、更新 1 筆財產')
        self.assertEqual(Asset.objects.count(),2)

    def test_default_add_only_does_not_accept_forged_preview_overwrite_flag(self):
        asset = self.existing()
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row()])
        response = self.confirm(client,batch,overwrite_existing='on')
        self.assertContains(response,'已存在')
        asset.refresh_from_db()
        self.assertEqual(asset.name,'原有筆電')

    def test_duplicate_workbook_numbers_never_overwrite_twice(self):
        asset = self.existing()
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row(),self.valid_row('pca-01-001')],{'overwrite_existing':'on'})
        self.assertContains(self.confirm(client,batch),'財產編號不可重複')
        asset.refresh_from_db()
        self.assertEqual(asset.name,'原有筆電')

    def test_stale_preview_rolls_back_new_rows_and_audit(self):
        asset = self.existing()
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row('PCA-01-002'),self.valid_row()],{'overwrite_existing':'on'})
        asset.name = '其他人剛修改'
        asset.save()
        response = self.confirm(client,batch)
        self.assertContains(response,'預覽後已有異動')
        self.assertFalse(Asset.objects.filter(asset_no='PCA-01-002').exists())
        self.assertFalse(OperationLog.objects.filter(action='create',model_label='assets.asset',changes__asset_no__after='PCA-01-002').exists())
        asset.refresh_from_db()
        self.assertEqual(asset.name,'其他人剛修改')
        self.assertTrue(AssetImportBatch.objects.filter(pk=batch.pk).exists())

    def test_target_appearing_after_preview_is_not_silently_overwritten(self):
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row()],{'overwrite_existing':'on'})
        asset = self.existing()
        self.assertContains(self.confirm(client,batch),'預覽後已有異動')
        asset.refresh_from_db()
        self.assertEqual(asset.name,'原有筆電')

    def test_changed_key_requires_new_preview(self):
        self.existing()
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row()],{'overwrite_existing':'on'})
        self.assertContains(self.confirm(client,batch,**{'rows-0-asset_no':'DIFFERENT'}),'不可變更財產編號')
        self.assertFalse(Asset.objects.filter(asset_no='DIFFERENT').exists())

    def test_ambiguous_existing_case_variants_are_rejected(self):
        self.existing()
        self.existing('pca-01-001')
        response = self.client_for(self.manager).post(reverse('asset_bulk_upload'),{
            'excel_file':workbook_upload([self.valid_row()]),'overwrite_existing':'on'})
        self.assertContains(response,'對應多筆既有資料')
        self.assertFalse(AssetImportBatch.objects.exists())

    @override_settings(DEBUG=False)
    def test_production_hides_and_rejects_test_settings_for_both_uploads(self):
        client = self.client_for(self.manager)
        for route in ['asset_bulk_upload','registration_bulk_upload']:
            client = self.client_for(self.manager if route == 'asset_bulk_upload' else self.staff)
            response = client.get(reverse(route))
            for text in ['測試環境設定','name="testing_compatibility"','name="fallback_department"']:
                self.assertNotContains(response,text)
            response = client.post(reverse(route),{'excel_file':workbook_upload([self.valid_row()]),
                'testing_compatibility':'on','fallback_department':self.it.pk})
            self.assertContains(response,'正式環境不支援測試相容模式')
        self.assertFalse(AssetImportBatch.objects.exists())

    @override_settings(DEBUG=True)
    def test_development_test_batch_cannot_be_confirmed_in_production(self):
        client = self.client_for(self.manager)
        batch = self.upload_for_preview(client,[self.valid_row()],{'testing_compatibility':'on','fallback_department':self.it.pk})
        self.assertTrue(batch.testing_compatibility)
        with override_settings(DEBUG=False):
            self.assertEqual(self.confirm(client,batch).status_code,403)
        self.assertFalse(Asset.objects.exists())

    def test_upload_area_contains_the_single_real_file_input(self):
        response = self.client_for(self.manager).get(reverse('asset_bulk_upload'))
        self.assertContains(response,'data-upload-drop')
        self.assertContains(response,'name="excel_file"',count=1)
        self.assertContains(response,'assets/import-upload.js')
