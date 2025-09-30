from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0003_athleteregistration_rule_set'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='is_free',
            field=models.BooleanField(default=False),
        ),
    ]
