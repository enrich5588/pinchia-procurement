from django import template

from assets.permissions import can_monitor_database as can_monitor


register = template.Library()


@register.simple_tag
def can_monitor_database(user):
    return can_monitor(user)
