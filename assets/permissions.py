from organization.models import user_department


MANAGEMENT_DEPARTMENT_NAME = "管理部"


def can_manage_assets(user):
    """管理部與系統管理員可檢視全公司財產並進行管理。"""
    department = user_department(user)
    return user.is_superuser or (
        department is not None and department.name == MANAGEMENT_DEPARTMENT_NAME
    )
