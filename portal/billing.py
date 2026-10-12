"""Billing: charges per session, payments, balances and monthly statements."""
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import BillingProfile


def suggested_amount(minutes, profile=None):
    profile = profile or BillingProfile.get()
    return (profile.hourly_rate * Decimal(minutes) / 60).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _by_currency(items):
    totals = defaultdict(Decimal)
    for item in items:
        totals[item.currency] += item.amount
    return dict(totals)


def account(student):
    """Everything the account page needs, with totals per currency."""
    charges = list(student.charges.all())
    payments = list(student.payments.all())
    charged, paid = _by_currency(charges), _by_currency(payments)
    currencies = sorted(set(charged) | set(paid)) or [BillingProfile.get().currency]
    balances = [
        {"currency": c, "charged": charged.get(c, Decimal(0)), "paid": paid.get(c, Decimal(0)),
         "balance": charged.get(c, Decimal(0)) - paid.get(c, Decimal(0))}
        for c in currencies
    ]
    months = defaultdict(list)
    for charge in charges:
        months[(charge.date.year, charge.date.month)].append(charge)
    statements = [
        {"year": y, "month": m, "start": date(y, m, 1), "count": len(items), "totals": _by_currency(items)}
        for (y, m), items in sorted(months.items(), reverse=True)
    ]
    return {"balances": balances, "statements": statements, "charges": charges[::-1], "payments": payments[::-1]}


def statement(student, year, month):
    charges = list(student.charges.filter(date__year=year, date__month=month))
    return {"charges": charges, "totals": _by_currency(charges), "start": date(year, month, 1)}
