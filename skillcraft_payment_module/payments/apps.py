from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    # Set here (not in project settings) so the app is self-contained and
    # produces the same migrations in any project.
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"
    verbose_name = "SkillCraft Payments (Razorpay)"
