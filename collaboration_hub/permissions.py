from organization.models import user_department
from procurement.permissions import MANAGEMENT_DEPARTMENT_NAME


def can_manage_collaboration_tasks(user):
    department = user_department(user)
    return user.is_superuser or (
        department is not None and department.name == MANAGEMENT_DEPARTMENT_NAME
    )


def can_view_collaboration_task(user, task):
    if can_manage_collaboration_tasks(user):
        return True
    department = user_department(user)
    return department is not None and task.assigned_department_id == department.pk
