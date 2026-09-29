"""Each endpoint runs a fixed number of queries, however many rows it returns."""

import pytest
from django.urls import reverse

from tests.factories import CommentFactory, TaskFactory, UserFactory

pytestmark = pytest.mark.django_db

ROWS = 15


@pytest.fixture
def tasks(user, other_user):
    tasks = TaskFactory.create_batch(ROWS, assignee=other_user)
    for task in tasks:
        CommentFactory(task=task, author=other_user)
    return tasks


@pytest.mark.usefixtures("tasks")
def test_task_list(auth_client, django_assert_num_queries):
    with django_assert_num_queries(1):  # tasks joined with author and assignee
        response = auth_client.get(reverse("task-list"))

    assert len(response.data["results"]) == ROWS


@pytest.mark.usefixtures("tasks")
def test_filtered_task_list_next_page(auth_client, other_user, django_assert_num_queries):
    first = auth_client.get(reverse("task-list"), {"assignee": other_user.pk, "page_size": 5})

    with django_assert_num_queries(2):  # the assignee filter value, tasks
        response = auth_client.get(first.data["next"])

    assert len(response.data["results"]) == 5


def test_task_detail(auth_client, tasks, django_assert_num_queries):
    with django_assert_num_queries(1):
        auth_client.get(reverse("task-detail", args=[tasks[0].pk]))


def test_comment_list(auth_client, django_assert_num_queries):
    task = TaskFactory()
    CommentFactory.create_batch(ROWS, task=task)

    with django_assert_num_queries(3):  # the task, COUNT, comments joined with authors
        response = auth_client.get(reverse("task-comment-list", args=[task.pk]))

    assert len(response.data["results"]) == ROWS


def test_comment_detail(auth_client, django_assert_num_queries):
    comment = CommentFactory()

    with django_assert_num_queries(2):  # the task, the comment joined with its author
        auth_client.get(reverse("task-comment-detail", args=[comment.task_id, comment.pk]))


def test_user_list(auth_client, django_assert_num_queries):
    UserFactory.create_batch(ROWS)

    with django_assert_num_queries(2):  # COUNT, users
        response = auth_client.get(reverse("user-list"))

    assert len(response.data["results"]) == ROWS + 1


def test_user_detail(auth_client, other_user, django_assert_num_queries):
    with django_assert_num_queries(1):
        auth_client.get(reverse("user-detail", args=[other_user.pk]))
