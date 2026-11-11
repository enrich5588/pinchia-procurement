from organization.permission_catalog import MANAGEMENT_DEPARTMENT_NAME
from organization.permissions import can_manage


def can_manage_office_supply_applications(user):
    return can_manage(user, "supplies")


def can_manage_equipment_applications(user):
    """設備申請沿用採購申請專區的管理與事業發展部權限。"""
    return can_manage(user, "equipment")
