import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.tasks.models import Comment, Task

DEMO_PASSWORD = "demo-pass-123"
DEMO_USERS = ["alice", "bob", "carol"]


class Command(BaseCommand):
    help = "Create demo users, tasks and comments. Safe to run repeatedly."

    @transaction.atomic
    def handle(self, *args, **options):
        users = {name: self._get_or_create_user(name) for name in DEMO_USERS}
        today = timezone.localdate()

        demo_tasks = [
            (
                "Prepare sprint demo",
                "alice",
                "bob",
                Task.Priority.HIGH,
                2,
                Task.Status.IN_PROGRESS,
            ),
            ("Fix flaky login test", "bob", "carol", Task.Priority.MEDIUM, 5, Task.Status.TODO),
            ("Update onboarding docs", "carol", None, Task.Priority.LOW, None, Task.Status.TODO),
            ("Rotate API keys", "alice", "alice", Task.Priority.HIGH, -1, Task.Status.DONE),
        ]
        for title, author, assignee, priority, due_in_days, status in demo_tasks:
            task, created = Task.objects.get_or_create(
                title=title,
                author=users[author],
                defaults={
                    "assignee": users.get(assignee),
                    "priority": priority,
                    "status": status,
                    "due_date": (
                        today + datetime.timedelta(days=due_in_days)
                        if due_in_days is not None
                        else None
                    ),
                },
            )
            if created:
                Comment.objects.create(
                    task=task, author=users["bob"], text="I can help with this."
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: users {', '.join(DEMO_USERS)} "
                f"(password: {DEMO_PASSWORD}), {Task.objects.count()} tasks."
            )
        )

    @staticmethod
    def _get_or_create_user(username: str):
        user, created = get_user_model().objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
        return user
