# -*- coding: utf-8 -*-
# Generated by Django 1.10.1 on 2016-09-10 16:49
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='notification',
            options={'ordering': ['-timestamp']},
        ),
    ]
