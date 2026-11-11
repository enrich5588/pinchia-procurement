from organization.permission_catalog import MANAGEMENT_DEPARTMENT_NAME
from organization.permissions import can_manage, has_permission


def can_manage_assets(user):
    """管理與事業發展部與系統管理員可檢視全公司財產並進行管理。"""
    return can_manage(user, "assets")


def can_manage_registrations(user):
    return can_manage(user, "registrations")


def can_monitor_database(user):
    return has_permission(user, "database.monitor")
