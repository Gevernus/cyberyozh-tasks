from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Count, F

from apps.tasks.models import Comment, Task

pytestmark = pytest.mark.django_db

PASSWORD = "Load-test-pass-42"


def seed_bulk(*args: str) -> str:
    out = StringIO()
    call_command("seed_bulk", "--password", PASSWORD, *args, stdout=out)
    return out.getvalue()


def test_creates_users_and_tasks_in_batches(django_user_model):
    output = seed_bulk("--tasks", "250", "--users", "7", "--batch-size", "100", "--seed", "1")

    assert Task.objects.count() == 250
    assert django_user_model.objects.filter(username__startswith="load").count() == 7
    assert django_user_model.objects.get(username="load00006").check_password(PASSWORD)
    assert "Tasks: 250/250" in output


def test_comment_counters_match_the_comments():
    seed_bulk("--tasks", "300", "--users", "3", "--seed", "2")

    mismatched = Task.objects.annotate(actual=Count("comments")).exclude(
        comments_count=F("actual")
    )
    assert Comment.objects.exists()
    assert not mismatched.exists()


def test_completed_tasks_have_a_completion_time():
    seed_bulk("--tasks", "100", "--users", "2", "--seed", "3")

    assert not Task.objects.filter(status=Task.Status.DONE, completed_at=None).exists()
    assert not Task.objects.exclude(status=Task.Status.DONE).exclude(completed_at=None).exists()


def test_runs_again_without_duplicating_users(django_user_model):
    seed_bulk("--tasks", "10", "--users", "3")
    seed_bulk("--tasks", "10", "--users", "3")

    assert django_user_model.objects.count() == 3
    assert Task.objects.count() == 20


def test_rejects_a_weak_password():
    with pytest.raises(CommandError, match="Password rejected"):
        call_command("seed_bulk", "--password", "short", "--tasks", "1", stdout=StringIO())
