"""Pre-fill billing details from PrepMe's existing invoice (editable later under Billing → Settings)."""
from decimal import Decimal

from django.db import migrations

PAYMENT_DETAILS = "341 - Itaú Unibanco\nAgência: 0196\nConta-corrente: 14044-6"


def create_profile(apps, schema_editor):
    BillingProfile = apps.get_model("portal", "BillingProfile")
    if not BillingProfile.objects.exists():
        BillingProfile.objects.create(
            company_name="Prepme Servicos Educacionais Eireli",
            tax_id="30.466.564/0001-85",
            payment_details=PAYMENT_DETAILS,
            hourly_rate=Decimal("2750.00"),
            currency="BRL",
        )


class Migration(migrations.Migration):
    dependencies = [("portal", "0004_billingprofile_application_aid_currency_and_more")]
    operations = [migrations.RunPython(create_profile, migrations.RunPython.noop)]
