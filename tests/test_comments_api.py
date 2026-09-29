import pytest
from django.urls import reverse
from rest_framework import status

from apps.tasks.models import Comment
from tests.factories import CommentFactory, TaskFactory

pytestmark = pytest.mark.django_db


def list_url(task) -> str:
    return reverse("task-comment-list", args=[task.pk])


def detail_url(comment: Comment) -> str:
    return reverse("task-comment-detail", args=[comment.task_id, comment.pk])


def test_any_user_can_comment_on_a_task(auth_client, user):
    task = TaskFactory()

    response = auth_client.post(list_url(task), {"text": "On it"})

    assert response.status_code == status.HTTP_201_CREATED
    comment = Comment.objects.get(pk=response.data["id"])
    assert comment.task == task
    assert comment.author == user
    assert response.data["author"]["username"] == user.username


def test_comment_text_is_required(auth_client):
    response = auth_client.post(list_url(TaskFactory()), {"text": ""})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_list_returns_only_comments_of_the_task_in_chronological_order(auth_client):
    task = TaskFactory()
    first = CommentFactory(task=task, text="first")
    second = CommentFactory(task=task, text="second")
    CommentFactory(text="other task")

    response = auth_client.get(list_url(task))

    assert response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in response.data["results"]] == [first.pk, second.pk]


def test_comments_are_paginated_by_cursor_oldest_first(auth_client):
    task = TaskFactory()
    comments = CommentFactory.create_batch(5, task=task)

    pages = [auth_client.get(list_url(task), {"page_size": 2}).data]
    while pages[-1]["next"]:
        pages.append(auth_client.get(pages[-1]["next"]).data)

    assert set(pages[0]) == {"next", "previous", "results"}
    assert [len(page["results"]) for page in pages] == [2, 2, 1]
    assert [item["id"] for page in pages for item in page["results"]] == [c.pk for c in comments]


def test_comments_of_missing_task_return_404(auth_client):
    url = reverse("task-comment-list", args=[999])

    assert auth_client.get(url).status_code == status.HTTP_404_NOT_FOUND
    assert auth_client.post(url, {"text": "hi"}).status_code == status.HTTP_404_NOT_FOUND


def test_comment_is_not_reachable_through_another_task(auth_client):
    comment = CommentFactory()
    other_task = TaskFactory()

    url = reverse("task-comment-detail", args=[other_task.pk, comment.pk])

    assert auth_client.get(url).status_code == status.HTTP_404_NOT_FOUND


def test_author_can_edit_comment(auth_client, user):
    comment = CommentFactory(author=user)

    response = auth_client.patch(detail_url(comment), {"text": "Edited"})

    assert response.status_code == status.HTTP_200_OK
    comment.refresh_from_db()
    assert comment.text == "Edited"


def test_author_can_delete_comment(auth_client, user):
    comment = CommentFactory(author=user)

    response = auth_client.delete(detail_url(comment))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not Comment.objects.filter(pk=comment.pk).exists()


def test_task_author_cannot_edit_someone_elses_comment(auth_client, user, other_user):
    comment = CommentFactory(task=TaskFactory(author=user), author=other_user)

    assert auth_client.patch(detail_url(comment), {"text": "x"}).status_code == 403
    assert auth_client.delete(detail_url(comment)).status_code == 403
    assert Comment.objects.filter(pk=comment.pk, text=comment.text).exists()


def test_other_users_cannot_delete_a_comment(auth_client, other_user):
    comment = CommentFactory(author=other_user)

    response = auth_client.delete(detail_url(comment))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert Comment.objects.filter(pk=comment.pk).exists()
    comment.task.refresh_from_db()
    assert comment.task.comments_count == 1


def test_comment_cannot_be_moved_to_another_task(auth_client, user):
    comment = CommentFactory(author=user)
    other_task = TaskFactory()

    auth_client.patch(detail_url(comment), {"task": other_task.pk})

    comment.refresh_from_db()
    assert comment.task_id != other_task.pk


def test_anonymous_user_cannot_read_comments(api_client):
    assert api_client.get(list_url(TaskFactory())).status_code == 401


def test_task_shows_the_number_of_comments(auth_client, user):
    task = TaskFactory()
    task_url = reverse("task-detail", args=[task.pk])

    created = auth_client.post(list_url(task), {"text": "one"})
    auth_client.post(list_url(task), {"text": "two"})
    assert auth_client.get(task_url).data["comments_count"] == 2

    auth_client.delete(reverse("task-comment-detail", args=[task.pk, created.data["id"]]))
    assert auth_client.get(task_url).data["comments_count"] == 1


def test_comment_text_is_bounded(auth_client):
    task = TaskFactory()

    assert auth_client.post(list_url(task), {"text": "x" * 2_000}).status_code == 201
    response = auth_client.post(list_url(task), {"text": "x" * 2_001})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "text" in response.data
