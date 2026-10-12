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
    # essays
    "brainstorming": "muted",
    "drafting": "",
    "ready_for_review": "warn",
    "revising": "warn",
    "final": "ok",
}


@register.filter
def chip_class(status):
    return CHIP_CLASSES.get(status, "")


@register.filter
def pct(value):
    """0.0361 -> '3.6%'. Blank when unknown."""
    if value is None or value == "":
        return "—"
    number = float(value) * 100
    return f"{number:.1f}%" if number < 10 else f"{number:.0f}%"


CURRENCY_SYMBOLS = {"USD": "US$", "GBP": "£", "EUR": "€", "CAD": "C$", "CHF": "CHF ", "BRL": "R$ "}


@register.filter
def amount(value, currency="BRL"):
    """Money with cents, as on PrepMe's invoices: R$ 2,750.00"""
    if value is None or value == "":
        return "—"
    symbol = CURRENCY_SYMBOLS.get((currency or "BRL").upper(), f"{currency} ")
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"


@register.filter
def money(value, currency="USD"):
    if value is None or value == "":
        return "—"
    symbol = CURRENCY_SYMBOLS.get((currency or "USD").upper(), f"{currency} ")
    return f"{symbol}{int(value):,}"


@register.filter
def num(value):
    return f"{int(value):,}" if value not in (None, "") else "—"


@register.filter
def score_range(low, high):
    if low is None and high is None:
        return "—"
    return f"{low if low is not None else '?'}–{high if high is not None else '?'}"
