"""
Small compatibility helpers so the app works on Django 4.2 LTS and Django 5.x.

Django 5.1 renamed ``CheckConstraint(check=...)`` to
``CheckConstraint(condition=...)``. The main SkillCraft.AI project may run
either version, so models and migrations build constraints through this
helper instead of using the keyword directly.
"""
import django
from django.db import models


def check_constraint(q, name):
    """Return a CheckConstraint using the keyword supported by this Django."""
    if django.VERSION >= (5, 1):
        return models.CheckConstraint(condition=q, name=name)
    return models.CheckConstraint(check=q, name=name)  # pragma: no cover
