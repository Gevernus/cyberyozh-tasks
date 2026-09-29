import importlib

import pytest
from django.apps import apps as django_apps

from apps.tasks.models import Comment, StatusTransitionError, Task
from tests.factories import CommentFactory, TaskFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_new_task_defaults():
    task = TaskFactory()

    assert task.status == Task.Status.TODO
    assert task.priority == Task.Priority.MEDIUM
    assert task.assignee is None
    assert task.completed_at is None
    assert str(task) == task.title


def test_complete_sets_completed_at():
    task = TaskFactory()

    task.complete()
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

    assert str(comment) == f"Comment #{comment.pk} on task #{comment.task_id}"

    comment.task.delete()

    assert not type(comment).objects.filter(pk=comment.pk).exists()


def test_complete_rejects_completed_task():
    task = TaskFactory(status=Task.Status.DONE)

    with pytest.raises(StatusTransitionError):
        task.complete()


def test_reopen_rejects_open_task():
    task = TaskFactory()

    with pytest.raises(StatusTransitionError):
        task.reopen()


def test_status_change_checks_the_stored_state_not_a_stale_instance():
    task = TaskFactory()
    Task.objects.filter(pk=task.pk).update(status=Task.Status.DONE)

    with pytest.raises(StatusTransitionError):
        task.complete()


# --- Comment counter ----------------------------------------------------------


def comments_count(task: Task) -> int:
    return Task.objects.values_list("comments_count", flat=True).get(pk=task.pk)


def test_comments_count_follows_creation_and_deletion():
    task = TaskFactory()
    first, _ = CommentFactory.create_batch(2, task=task)
    assert comments_count(task) == 2

    first.text = "Edited"
    first.save()
    assert comments_count(task) == 2

    first.delete()
    assert comments_count(task) == 1

    Comment.objects.filter(task=task).delete()
    assert comments_count(task) == 0


def test_deleting_a_user_uncounts_their_comments_on_other_tasks():
    task = TaskFactory()
    commenter = UserFactory()
    CommentFactory.create_batch(2, task=task, author=commenter)
    CommentFactory(task=task)

    commenter.delete()

    assert comments_count(task) == 1


def test_deleting_tasks_with_comments_leaves_no_rows():
    tasks = TaskFactory.create_batch(2)
    for task in tasks:
        CommentFactory(task=task)

    tasks[0].delete()
    Task.objects.all().delete()

    assert not Comment.objects.exists()


def test_saving_a_stale_task_keeps_comments_added_meanwhile():
    task = TaskFactory()
    stale = Task.objects.get(pk=task.pk)
    CommentFactory(task=task)

    stale.title = "Renamed"
    stale.save()

    assert comments_count(task) == 1
    assert Task.objects.get(pk=task.pk).title == "Renamed"


def test_migration_backfills_comments_count():
    backfill = importlib.import_module("apps.tasks.migrations.0002_task_comments_count")
    busy, quiet = TaskFactory.create_batch(2)
    CommentFactory.create_batch(3, task=busy)
    Task.objects.update(comments_count=0)

    backfill.count_comments(django_apps, schema_editor=None)

    assert comments_count(busy) == 3
    assert comments_count(quiet) == 0
