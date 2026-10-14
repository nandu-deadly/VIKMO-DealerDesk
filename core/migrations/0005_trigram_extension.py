from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_dealer_user_order_confirmed_at_order_confirmed_by"),
    ]

    operations = [
        TrigramExtension(),
    ]

