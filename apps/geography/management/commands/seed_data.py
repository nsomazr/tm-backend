from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.compliance.models import TermsVersion
from apps.subscriptions.models import SubscriptionPlan


class Command(BaseCommand):
    help = "Seed Terra Meta with Tanzania geography, minerals, plans, and admin user"

    def handle(self, *args, **options):
        monthly, _ = SubscriptionPlan.objects.get_or_create(
            slug="monthly-standard",
            defaults={
                "name": "Monthly Standard",
                "description": "Terra insights, show-on-map, full AI, analytics, and 3 PDF downloads per month",
                "billing_cycle": "monthly",
                "price": 100000,
                "currency": "TZS",
                "included_report_downloads": 3,
            },
        )
        monthly.included_report_downloads = 3
        monthly.included_assistant_credits = 3000
        monthly.includes_chat_history = True
        monthly.max_explorable_minerals = 10
        monthly.description = (
            "More access to advanced Terra insights — 10 mineral deep-explores per month"
        )
        monthly.name = "Plus"
        monthly.price = 100000
        monthly.save(
            update_fields=[
                "name",
                "description",
                "price",
                "included_report_downloads",
                "included_assistant_credits",
                "includes_chat_history",
                "max_explorable_minerals",
            ]
        )
        annual, _ = SubscriptionPlan.objects.get_or_create(
            slug="annual-standard",
            defaults={
                "name": "Annual Standard",
                "description": "Full year: Terra insights, show-on-map, full AI, analytics, and 10 PDF downloads",
                "billing_cycle": "annual",
                "price": 1800000,
                "currency": "TZS",
                "included_report_downloads": 10,
            },
        )
        annual.included_report_downloads = 10
        annual.included_assistant_credits = 5000
        annual.includes_chat_history = True
        annual.max_explorable_minerals = None
        annual.description = (
            "Unlimited mineral exploration all year with full Terra intelligence"
        )
        annual.name = "Pro"
        annual.price = 1800000
        annual.save(
            update_fields=[
                "name",
                "description",
                "price",
                "included_report_downloads",
                "included_assistant_credits",
                "includes_chat_history",
                "max_explorable_minerals",
            ]
        )

        starter, _ = SubscriptionPlan.objects.get_or_create(
            slug="monthly-starter",
            defaults={
                "name": "Monthly Starter",
                "description": "Explore up to 5 minerals per month with Terra insights and map tools",
                "billing_cycle": "monthly",
                "price": 50000,
                "currency": "TZS",
                "included_report_downloads": 1,
                "included_assistant_credits": 1500,
                "includes_chat_history": True,
                "max_explorable_minerals": 5,
            },
        )
        starter.name = "Starter"
        starter.description = "Keep exploring — 5 mineral deep-explores per month"
        starter.max_explorable_minerals = 5
        starter.included_assistant_credits = 1500
        starter.included_report_downloads = 1
        starter.includes_chat_history = True
        starter.is_active = True
        starter.price = 50000
        starter.save(
            update_fields=[
                "name",
                "description",
                "price",
                "max_explorable_minerals",
                "included_assistant_credits",
                "included_report_downloads",
                "includes_chat_history",
                "is_active",
            ]
        )
        TermsVersion.objects.get_or_create(
            version="1.0",
            defaults={
                "title": "Terra Meta Terms of Service",
                "content": "By using Terra Meta you agree to comply with Tanzanian mining regulations and data licensing terms.",
                "is_active": True,
            },
        )

        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@5ggeology.com",
                "role": User.Role.SUPER_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "profile_complete": True,
            },
        )
        admin_user.email = "admin@5ggeology.com"
        admin_user.profile_complete = True
        if created:
            admin_user.set_password("admin123")
            admin_user.save()
            self.stdout.write(
                self.style.SUCCESS("Created admin: admin@5ggeology.com / admin123")
            )
        else:
            if admin_user.role not in (User.Role.SUPER_ADMIN, User.Role.ADMIN):
                admin_user.role = User.Role.SUPER_ADMIN
                admin_user.is_staff = True
                admin_user.is_superuser = True
            admin_user.set_password("admin123")
            admin_user.save()
            self.stdout.write(
                self.style.SUCCESS("Admin ready: admin@5ggeology.com / admin123")
            )

        self.stdout.write(self.style.SUCCESS("Seed data loaded successfully."))

