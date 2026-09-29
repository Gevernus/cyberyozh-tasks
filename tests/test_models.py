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


def test_deleting_comments_of_several_tasks_uncounts_each_task():
    busy, quiet, untouched = TaskFactory.create_batch(3)
    CommentFactory.create_batch(3, task=busy)
    CommentFactory(task=quiet)
    CommentFactory(task=untouched)

    deleted = Comment.objects.exclude(task=untouched).delete()

    assert deleted == (4, {"tasks.Comment": 4})
    assert [comments_count(task) for task in (busy, quiet, untouched)] == [0, 0, 1]


def test_a_comment_deleted_twice_is_uncounted_once():
    comment, _ = CommentFactory.create_batch(2)
    CommentFactory(task=comment.task)
    stale = Comment.objects.get(pk=comment.pk)

    comment.delete()
    stale.delete()

    assert comments_count(comment.task) == 1


def test_deleting_a_user_uncounts_their_comments_on_other_tasks():
    commenter = UserFactory()
    first, second = TaskFactory.create_batch(2)
    CommentFactory.create_batch(2, task=first, author=commenter)
    CommentFactory(task=first)
    CommentFactory(task=second, author=commenter)
    CommentFactory.create_batch(2, task=TaskFactory(author=commenter))

    commenter.delete()

    assert [comments_count(first), comments_count(second)] == [1, 0]
    assert Comment.objects.count() == 1


def test_deleting_users_who_comment_on_each_other_keeps_other_counters():
    alice, bob = UserFactory.create_batch(2)
    third_party = TaskFactory()
    CommentFactory(task=TaskFactory(author=alice), author=bob)
    CommentFactory(task=TaskFactory(author=bob), author=alice)
    CommentFactory(task=third_party, author=alice)
    CommentFactory(task=third_party)

    type(alice).objects.filter(pk__in=[alice.pk, bob.pk]).delete()

    assert list(Task.objects.values_list("pk", "comments_count")) == [(third_party.pk, 1)]


@pytest.mark.parametrize("tasks", [1, 20])
def test_deleting_a_user_takes_the_same_queries_however_many_comments(
    tasks, django_assert_num_queries
):
    user = UserFactory()
    for task in TaskFactory.create_batch(tasks, author=user):
        CommentFactory.create_batch(3, task=task)
    for task in TaskFactory.create_batch(tasks):
        CommentFactory.create_batch(2, task=task, author=user)

    # The user's tasks, then per table one DELETE or UPDATE: no query per comment.
    with django_assert_num_queries(11):
        user.delete()


@pytest.mark.parametrize("comments", [1, 20])
def test_deleting_a_task_does_not_load_its_comments(comments, django_assert_num_queries):
    task = TaskFactory()
    CommentFactory.create_batch(comments, task=task)

    with django_assert_num_queries(2):  # the comments, the task
        task.delete()


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
