from organization.models import user_department
from procurement.permissions import MANAGEMENT_DEPARTMENT_NAME
from organization.permissions import can_manage, has_permission


def can_manage_collaboration_tasks(user):
    return can_manage(user, "collaboration")


def can_view_collaboration_task(user, task):
    if not has_permission(user, "collaboration.access"):
        return False
    if can_manage_collaboration_tasks(user):
        return True
    department = user_department(user)
    return department is not None and task.assigned_department_id == department.pk
