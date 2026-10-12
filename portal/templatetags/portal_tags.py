from django import template

register = template.Library()

CHIP_CLASSES = {
    # tasks
    "todo": "",
    "in_progress": "warn",
    "done": "ok",
    # applications
    "pending_add": "warn",
    "active": "ok",
    "pending_removal": "danger",
    "removed": "muted",
    "declined": "muted",
    # documents
    "not_started": "muted",
    "requested": "",
    "ready": "ok",
    "submitted": "ok",
    "not_needed": "muted",
}


@register.filter
def chip_class(status):
    return CHIP_CLASSES.get(status, "")
