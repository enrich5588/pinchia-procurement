from django import template

from assets.permissions import can_manage_assets


register = template.Library()


@register.simple_tag
def can_monitor_database(user):
    return can_manage_assets(user)
