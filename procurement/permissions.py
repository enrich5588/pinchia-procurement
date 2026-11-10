from organization.models import user_department


MANAGEMENT_DEPARTMENT_NAME = "管理部"


def can_manage_office_supply_applications(user):
    department = user_department(user)
    return user.is_superuser or (
        department is not None and department.name == MANAGEMENT_DEPARTMENT_NAME
    )


def can_manage_equipment_applications(user):
    """設備申請沿用採購申請專區的管理部權限。"""
    return can_manage_office_supply_applications(user)
