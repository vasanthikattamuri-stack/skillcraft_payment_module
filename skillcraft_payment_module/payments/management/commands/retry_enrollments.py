"""
Retry enrollment activation for paid orders whose enrollment failed.

Usage:
    python manage.py retry_enrollments            # retry all
    python manage.py retry_enrollments --dry-run  # only list them

Safe to run any number of times (e.g. from a cron job): an order is enrolled
at most once because of the `enrollment_activated` flag.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from payments.models import PaymentOrder
from payments.services import activate_enrollment_after_payment


class Command(BaseCommand):
    help = "Retry LMS enrollment activation for PAID orders that are not yet enrolled."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List orders without changing anything.")

    def handle(self, *args, **options):
        pending_ids = list(
            PaymentOrder.objects.filter(
                status=PaymentOrder.Status.PAID, enrollment_activated=False
            ).values_list("pk", flat=True)
        )
        if not pending_ids:
            self.stdout.write(self.style.SUCCESS("No paid orders are waiting for enrollment."))
            return

        activated = failed = 0
        for pk in pending_ids:
            with transaction.atomic():
                order = PaymentOrder.objects.select_for_update().get(pk=pk)
                if options["dry_run"]:
                    self.stdout.write(f"Would retry: {order.internal_order_id}")
                    continue
                if activate_enrollment_after_payment(order):
                    activated += 1
                    self.stdout.write(f"Activated: {order.internal_order_id}")
                elif not order.enrollment_activated:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"Still failing: {order.internal_order_id}"))

        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Done. Activated={activated}, still failing={failed}."))
