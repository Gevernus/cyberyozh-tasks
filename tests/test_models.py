import pytest

from apps.tasks.models import Task
from tests.factories import CommentFactory, TaskFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_new_task_defaults():
    task = TaskFactory()

    assert task.status == Task.Status.TODO
    assert task.priority == Task.Priority.MEDIUM
    assert task.assignee is None
    assert task.completed_at is None
    assert str(task) == task.title


def test_mark_completed_sets_completed_at():
    task = TaskFactory()

    task.mark_completed()
    task.refresh_from_db()

    assert task.is_completed
    assert task.completed_at is not None


def test_reopen_clears_completed_at():
    task = TaskFactory(status=Task.Status.DONE)
    assert task.completed_at is not None

    task.reopen()
    task.refresh_from_db()

    assert task.status == Task.Status.TODO
    assert task.completed_at is None


def test_completed_at_is_preserved_on_unrelated_updates():
    task = TaskFactory(status=Task.Status.DONE)
    completed_at = task.completed_at

    task.title = "Renamed"
    task.save()
    task.refresh_from_db()

    assert task.completed_at == completed_at


def test_deleting_assignee_unassigns_task():
    assignee = UserFactory()
    task = TaskFactory(assignee=assignee)

    assignee.delete()
    task.refresh_from_db()

    assert task.assignee is None


def test_deleting_task_deletes_comments():
    comment = CommentFactory()

    comment.task.delete()

    assert not type(comment).objects.filter(pk=comment.pk).exists()
