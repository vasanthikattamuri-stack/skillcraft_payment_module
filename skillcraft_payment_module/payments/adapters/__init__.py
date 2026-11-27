"""
LMS integration adapters.

The payments module never imports the LMS Course / Enrollment models
directly. Instead it talks to two small "adapter" classes whose dotted paths
are configured in settings:

    PAYMENTS_COURSE_CATALOG_ADAPTER = "payments.adapters.demo.DemoCourseCatalogAdapter"
    PAYMENTS_ENROLLMENT_ADAPTER     = "payments.adapters.demo.DemoEnrollmentAdapter"

The main SkillCraft.AI project replaces these with its own classes (see
docs/MAIN_PROJECT_INTEGRATION.md) without changing any payment code.
"""
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .. import conf
from .base import BaseCourseCatalogAdapter, BaseEnrollmentAdapter, CourseInfo

__all__ = [
    "BaseCourseCatalogAdapter",
    "BaseEnrollmentAdapter",
    "CourseInfo",
    "get_course_catalog",
    "get_enrollment_adapter",
]


def _load(path, base_class):
    try:
        klass = import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(f"Cannot import payments adapter {path!r}.") from exc
    if not issubclass(klass, base_class):
        raise ImproperlyConfigured(f"{path!r} must subclass {base_class.__name__}.")
    return klass()


def get_course_catalog():
    """Return the configured course catalog adapter instance."""
    return _load(conf.get_course_catalog_adapter_path(), BaseCourseCatalogAdapter)


def get_enrollment_adapter():
    """Return the configured enrollment adapter instance."""
    return _load(conf.get_enrollment_adapter_path(), BaseEnrollmentAdapter)
