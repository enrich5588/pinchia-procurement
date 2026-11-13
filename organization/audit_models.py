from django.db import models, transaction


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from .audit import snapshot, record_change
        with transaction.atomic(using=self.db):
            before = {obj.pk: snapshot(obj) for obj in self.select_for_update()}
            count = super().update(**kwargs)
            for obj in self.model._base_manager.using(self.db).filter(pk__in=before):
                record_change(obj, before[obj.pk], snapshot(obj))
            return count

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        from .audit import snapshot, record_change
        if ignore_conflicts or update_conflicts:
            raise ValueError('Audited bulk inserts require explicit create/update rather than silent conflict handling.')
        with transaction.atomic(using=self.db):
            result = super().bulk_create(objs, batch_size=batch_size, update_fields=update_fields, unique_fields=unique_fields)
            for obj in result:
                if obj.pk is None:
                    raise ValueError('Database did not return an identifier for the audited insert.')
                record_change(obj, {}, snapshot(obj), created=True)
            return result


class AuditedModel(models.Model):
    objects = AuditQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        with transaction.atomic(using=kwargs.get('using') or self._state.db or 'default'):
            return super().save(*args, **kwargs)
