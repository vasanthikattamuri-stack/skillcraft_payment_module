"""
=====================================================================
DEMO ADAPTERS - FOR THE STANDALONE DEMONSTRATION PROJECT ONLY
=====================================================================

The standalone project has no real Course or Enrollment models, so these
classes stand in for them:

* DemoCourseCatalogAdapter - a tiny in-memory list of DEMO courses.
  These are NOT real SkillCraft.AI courses.
* DemoEnrollmentAdapter    - does NOT create any enrollment. It only writes
  a log line so you can see when enrollment WOULD be activated.

In the main project, replace both with real adapters that use the LMS
models (see docs/MAIN_PROJECT_INTEGRATION.md, section "Connect the LMS").
"""
import logging

from .. import conf
from .base import BaseCourseCatalogAdapter, BaseEnrollmentAdapter, CourseInfo

logger = logging.getLogger("payments")

# DEMO DATA ONLY - identifiers used for local testing and Postman examples.
DEMO_COURSES = {
    "11": "DEMO Course 11",
    "12": "DEMO Course 12",
    "13": "DEMO Course 13",
    "14": "DEMO Course 14",
    "15": "DEMO Course 15",
}


class DemoCourseCatalogAdapter(BaseCourseCatalogAdapter):
    """DEMO: validates course ids against DEMO_COURSES."""

    def get_course(self, course_id):
        title = DEMO_COURSES.get(str(course_id))
        if title is None:
            return None
        return CourseInfo(course_id=str(course_id), title=title)

    def get_combo_course_ids(self):
        # DEMO PLACEHOLDER: read from settings.PAYMENTS_COMBO_COURSE_IDS.
        # The real combo list must come from the main LMS.
        return conf.get_combo_course_ids_setting()


class DemoEnrollmentAdapter(BaseEnrollmentAdapter):
    """DEMO: logs the enrollment that the real LMS adapter would create."""

    def activate_enrollment(self, *, user, order, course_ids):
        logger.info(
            "[DEMO ENROLLMENT ADAPTER] Would activate enrollment for user_id=%s "
            "order=%s courses=%s (no LMS records created in demo mode).",
            user.pk,
            order.internal_order_id,
            course_ids,
        )
