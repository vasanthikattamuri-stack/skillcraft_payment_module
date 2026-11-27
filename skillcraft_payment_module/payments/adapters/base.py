"""
Adapter interfaces (contracts) between the payments module and the LMS.

To integrate with the real SkillCraft.AI LMS, create subclasses of these two
classes inside the main project (for example ``courses/payment_adapters.py``)
and point the PAYMENTS_*_ADAPTER settings at them.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CourseInfo:
    """Minimal course information the payment module needs."""

    course_id: str
    title: str


class BaseCourseCatalogAdapter(ABC):
    """Answers questions about courses. Must NOT decide prices."""

    @abstractmethod
    def get_course(self, course_id):
        """
        Return a ``CourseInfo`` if ``course_id`` is a course that can be
        purchased individually right now, otherwise ``None``.
        ``course_id`` is always a string.
        """

    @abstractmethod
    def get_combo_course_ids(self):
        """
        Return the list of course identifiers (strings) included in the
        Complete Combo Package. Return an empty list if the combo is not
        available - the module will then refuse combo orders.
        """


class BaseEnrollmentAdapter(ABC):
    """Grants course access after a CAPTURED payment."""

    def user_has_access(self, *, user, course_ids):
        """
        Return True if ``user`` already has access to ALL ``course_ids``.
        Used to stop students paying twice for the same thing.
        Default: False (the module still checks its own paid orders).
        """
        return False

    @abstractmethod
    def activate_enrollment(self, *, user, order, course_ids):
        """
        Give ``user`` access to every course in ``course_ids``.

        Rules for implementers:
          * Called ONLY after the payment is verified AND captured.
          * Called inside a database transaction (savepoint). Raise an
            exception if enrollment fails - the payment stays recorded and
            ``python manage.py retry_enrollments`` can retry later.
          * Must be IDEMPOTENT: calling it twice must not create duplicate
            enrollments (use get_or_create / update_or_create).
        """
