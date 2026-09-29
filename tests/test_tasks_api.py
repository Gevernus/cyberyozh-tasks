from unittest import mock

import pytest
from django.urls import reverse
from rest_framework import status

from apps.tasks.models import Task
from core.pagination import NewestFirstCursorPagination
from tests.factories import CommentFactory, TaskFactory, UserFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("task-list")


def detail_url(task: Task) -> str:
    return reverse("task-detail", args=[task.pk])


def action_url(task: Task, name: str) -> str:
    return reverse(f"task-{name}", args=[task.pk])


# --- CRUD -------------------------------------------------------------------


def test_create_task_sets_current_user_as_author(auth_client, user, other_user):
    payload = {
        "title": "Write report",
        "description": "Quarterly numbers",
        "priority": Task.Priority.HIGH,
        "due_date": "2030-01-31",
        "assignee_id": other_user.pk,
    }

    response = auth_client.post(LIST_URL, payload)

    assert response.status_code == status.HTTP_201_CREATED
    task = Task.objects.get(pk=response.data["id"])
    assert task.author == user
    assert task.assignee == other_user
    assert response.data["author"]["username"] == user.username
    assert response.data["assignee"]["id"] == other_user.pk
    assert response.data["status"] == Task.Status.TODO
    assert response.data["comments_count"] == 0


def test_create_task_ignores_client_supplied_author(auth_client, user, other_user):
    response = auth_client.post(LIST_URL, {"title": "Mine", "author": other_user.pk})

    assert response.status_code == status.HTTP_201_CREATED
    assert Task.objects.get(pk=response.data["id"]).author == user


def test_create_task_requires_title(auth_client):
    response = auth_client.post(LIST_URL, {"description": "no title"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "title" in response.data


def test_create_task_rejects_inactive_assignee(auth_client):
    inactive = UserFactory(is_active=False)

    response = auth_client.post(LIST_URL, {"title": "X", "assignee_id": inactive.pk})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "assignee_id" in response.data


def test_list_tasks_includes_comment_counts(auth_client):
    task = TaskFactory()
    CommentFactory.create_batch(2, task=task)
    quiet = TaskFactory()

    response = auth_client.get(LIST_URL)

    assert response.status_code == status.HTTP_200_OK
    counts = {item["id"]: item["comments_count"] for item in response.data["results"]}
    assert counts == {task.pk: 2, quiet.pk: 0}


def walk_pages(client, url: str, **params) -> list[list[int]]:
    pages = []
    response = client.get(url, params)
    while True:
        assert response.status_code == status.HTTP_200_OK
        pages.append([item["id"] for item in response.data["results"]])
        if response.data["next"] is None:
            return pages
        response = client.get(response.data["next"])


def test_cursor_pages_list_every_task_once_newest_first(auth_client):
    tasks = TaskFactory.create_batch(5)

    pages = walk_pages(auth_client, LIST_URL, page_size=2)

    assert pages == [[t.pk for t in reversed(tasks)][i : i + 2] for i in (0, 2, 4)]


def test_cursor_pagination_survives_equal_timestamps(auth_client):
    tasks = TaskFactory.create_batch(5)
    Task.objects.update(created_at=tasks[0].created_at)

    pages = walk_pages(auth_client, LIST_URL, page_size=2)

    assert [pk for page in pages for pk in page] == sorted((t.pk for t in tasks), reverse=True)


def test_list_response_has_no_total_count(auth_client):
    TaskFactory()

    response = auth_client.get(LIST_URL)

    assert set(response.data) == {"next", "previous", "results"}


def test_page_size_is_capped(auth_client):
    TaskFactory.create_batch(3)

    with mock.patch.object(NewestFirstCursorPagination, "max_page_size", 2):
        response = auth_client.get(LIST_URL, {"page_size": 50})

    assert len(response.data["results"]) == 2


def test_invalid_cursor_returns_404(auth_client):
    response = auth_client.get(LIST_URL, {"cursor": "garbage"})

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_any_authenticated_user_can_read_a_task(auth_client):
    task = TaskFactory()

    response = auth_client.get(detail_url(task))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["title"] == task.title


def test_author_can_update_task(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.patch(detail_url(task), {"title": "Updated", "status": "in_progress"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["comments_count"] == 0
    task.refresh_from_db()
    assert task.title == "Updated"
    assert task.status == Task.Status.IN_PROGRESS


def test_author_can_complete_via_status_patch(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.patch(detail_url(task), {"status": Task.Status.DONE})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["completed_at"] is not None


def test_non_author_cannot_update_task(auth_client, other_user):
    task = TaskFactory(author=other_user)

    response = auth_client.patch(detail_url(task), {"title": "Hijacked"})

    assert response.status_code == status.HTTP_403_FORBIDDEN
    task.refresh_from_db()
    assert task.title != "Hijacked"


def test_assignee_cannot_edit_task_fields(client_for, user, other_user):
    task = TaskFactory(author=user, assignee=other_user)

    response = client_for(other_user).patch(detail_url(task), {"title": "Mine now"})

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_author_can_delete_task(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.delete(detail_url(task))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not Task.objects.filter(pk=task.pk).exists()


def test_non_author_cannot_delete_task(auth_client, other_user):
    task = TaskFactory(author=other_user)

    response = auth_client.delete(detail_url(task))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert Task.objects.filter(pk=task.pk).exists()


def test_missing_task_returns_404(auth_client):
    assert auth_client.get(reverse("task-detail", args=[999])).status_code == 404


def test_anonymous_user_cannot_access_tasks(api_client):
    assert api_client.get(LIST_URL).status_code == status.HTTP_401_UNAUTHORIZED


# --- Completion ---------------------------------------------------------------


def test_author_can_complete_task(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.post(action_url(task, "complete"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Task.Status.DONE
    assert response.data["completed_at"] is not None
    assert "comments_count" in response.data


def test_assignee_can_complete_task(client_for, user, other_user):
    task = TaskFactory(author=user, assignee=other_user)

    response = client_for(other_user).post(action_url(task, "complete"))

    assert response.status_code == status.HTTP_200_OK
    task.refresh_from_db()
    assert task.is_completed


def test_unrelated_user_cannot_complete_task(client_for, user, other_user):
    task = TaskFactory(author=user, assignee=other_user)
    stranger = UserFactory(username="mallory")

    response = client_for(stranger).post(action_url(task, "complete"))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    task.refresh_from_db()
    assert not task.is_completed


def test_completing_completed_task_is_rejected(auth_client, user):
    task = TaskFactory(author=user, status=Task.Status.DONE)

    response = auth_client.post(action_url(task, "complete"))

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_assignee_can_reopen_task(client_for, user, other_user):
    task = TaskFactory(author=user, assignee=other_user, status=Task.Status.DONE)

    response = client_for(other_user).post(action_url(task, "reopen"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Task.Status.TODO
    assert response.data["completed_at"] is None


def test_reopening_open_task_is_rejected(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.post(action_url(task, "reopen"))

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- Assignment ---------------------------------------------------------------


def test_author_can_assign_task(auth_client, user, other_user):
    task = TaskFactory(author=user)

    response = auth_client.post(action_url(task, "assign"), {"assignee_id": other_user.pk})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["assignee"]["id"] == other_user.pk
    assert "comments_count" in response.data
    task.refresh_from_db()
    assert task.assignee == other_user


def test_author_can_unassign_task(auth_client, user, other_user):
    task = TaskFactory(author=user, assignee=other_user)

    response = auth_client.post(action_url(task, "assign"), {"assignee_id": None})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["assignee"] is None


def test_assign_requires_existing_user(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.post(action_url(task, "assign"), {"assignee_id": 999})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_assign_requires_assignee_field(auth_client, user):
    task = TaskFactory(author=user)

    response = auth_client.post(action_url(task, "assign"), {})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_non_author_cannot_assign_task(client_for, user, other_user):
    task = TaskFactory(author=user)

    response = client_for(other_user).post(
        action_url(task, "assign"), {"assignee_id": other_user.pk}
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_assign_via_patch(auth_client, user, other_user):
    task = TaskFactory(author=user)

    response = auth_client.patch(detail_url(task), {"assignee_id": other_user.pk})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["assignee"]["username"] == other_user.username


# --- Limits -------------------------------------------------------------------


@pytest.mark.parametrize(("field", "limit"), [("title", 255), ("description", 10_000)])
def test_task_text_fields_are_bounded(auth_client, field, limit):
    payload = {"title": "Bounded", field: "x" * limit}
    assert auth_client.post(LIST_URL, payload).status_code == status.HTTP_201_CREATED

    payload[field] = "x" * (limit + 1)
    response = auth_client.post(LIST_URL, payload)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert field in response.data
