# Generated by Django 5.0.7 on 2024-08-15 10:56

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('images', '0002_image_assembled_image_b64_chunk_total_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='image',
            name='image',
        ),
    ]