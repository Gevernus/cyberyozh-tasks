import datetime
import os
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.tasks.models import Comment, Task

DEMO_USERS = ["alice", "bob", "carol"]


class Command(BaseCommand):
    help = "Create demo users, tasks and comments; each run sets a new password."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=os.environ.get("DEMO_PASSWORD"),
            help="Password for the demo users (default: $DEMO_PASSWORD, else a random one).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]
        if password is None:
            password = secrets.token_urlsafe(12)
        else:
            # An empty DEMO_PASSWORD is rejected rather than replaced.
            try:
                validate_password(password)
            except ValidationError as exc:
                raise CommandError(f"Demo password rejected: {' '.join(exc.messages)}") from exc
        users = {name: self._upsert_user(name, password) for name in DEMO_USERS}
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

        self.stdout.write(self.style.SUCCESS(f"Demo data ready: {Task.objects.count()} tasks."))
        self.stdout.write(f"Users: {', '.join(DEMO_USERS)}")
        if options["password"] is None:
            self.stdout.write(f"Password: {password}")

    @staticmethod
    def _upsert_user(username: str, password: str):
        user, _ = get_user_model().objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"}
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        return user
