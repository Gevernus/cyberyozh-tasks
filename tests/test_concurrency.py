import contextlib
import threading
import time
from collections.abc import Callable
from functools import partial
from unittest import mock

import pytest
from django.db import connection, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tasks.models import Comment, Task
from tests.factories import CommentFactory, TaskFactory

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="needs PostgreSQL: SQLite ignores SELECT ... FOR UPDATE",
    ),
    pytest.mark.django_db(transaction=True),
]

# How long the first writer waits for the second while holding its row lock.
RACE_WINDOW = 2.0


def run_in_threads(*targets: Callable[[], None]) -> None:
    """Run each target in a thread with its own database connection; wait for all."""

    def run(target: Callable[[], None]) -> None:
        try:
            target()
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(target,)) for target in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


@pytest.mark.parametrize(
    ("action", "initial_status", "final_status"),
    [
        ("complete", Task.Status.TODO, Task.Status.DONE),
        ("reopen", Task.Status.DONE, Task.Status.TODO),
    ],
)
def test_concurrent_status_changes_apply_once(
    client_for, user, action, initial_status, final_status
):
    task = TaskFactory(author=user, status=initial_status)
    url = reverse(f"task-{action}", args=[task.pk])
    both_passed_check = threading.Barrier(2, timeout=RACE_WINDOW)
    responses = []
    original_save = Task.save

    def save_after_rival_arrives(self, *args, **kwargs):
        # With the row lock the rival is blocked in SELECT ... FOR UPDATE, so this wait
        # times out; without it both requests would pass the check and write.
        with contextlib.suppress(threading.BrokenBarrierError):
            both_passed_check.wait()
        original_save(self, *args, **kwargs)

    def request() -> None:
        responses.append(client_for(user).post(url))

    with mock.patch.object(Task, "save", save_after_rival_arrives):
        run_in_threads(request, request)

    assert sorted(response.status_code for response in responses) == [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
    ]
    task.refresh_from_db()
    assert task.status == final_status
    assert (task.completed_at is not None) == task.is_completed


def test_concurrent_comments_are_all_counted(client_for, user):
    task = TaskFactory()
    url = reverse("task-comment-list", args=[task.pk])
    writers = 8
    start = threading.Barrier(writers, timeout=RACE_WINDOW)
    codes = []

    def comment() -> None:
        client = client_for(user)
        start.wait()
        codes.append(client.post(url, {"text": "me too"}).status_code)

    run_in_threads(*[comment] * writers)

    assert codes == [status.HTTP_201_CREATED] * writers
    task.refresh_from_db()
    assert task.comments_count == writers


def test_comments_deleted_by_two_requests_at_once_are_decremented_once():
    task = TaskFactory()
    selected = [comment.pk for comment in CommentFactory.create_batch(3, task=task)]
    CommentFactory(task=task)
    first_deleted = threading.Event()
    deleted = []

    def delete(first: bool) -> None:
        if not first:
            first_deleted.wait(RACE_WINDOW)
        with transaction.atomic():
            deleted.append(Comment.objects.filter(pk__in=selected).delete()[0])
            if first:
                first_deleted.set()
                # The rival reaches the same rows meanwhile and waits for this commit.
                time.sleep(RACE_WINDOW / 4)

    run_in_threads(partial(delete, first=True), partial(delete, first=False))

    assert deleted == [3, 0]
    task.refresh_from_db()
    assert task.comments_count == 1


@pytest.mark.parametrize("rival", ["token-refresh", "token-blacklist"])
def test_a_refresh_token_is_used_by_one_of_two_concurrent_requests(user, rival):
    refresh = str(RefreshToken.for_user(user))
    both_passed_check = threading.Barrier(2, timeout=RACE_WINDOW)
    codes = []
    original_blacklist = RefreshToken.blacklist

    def blacklist_after_rival_arrives(self):
        # As above: with the row lock the rival waits before its blacklist check.
        with contextlib.suppress(threading.BrokenBarrierError):
            both_passed_check.wait()
        return original_blacklist(self)

    def post(url_name: str) -> None:
        codes.append(APIClient().post(reverse(url_name), {"refresh": refresh}).status_code)

    with mock.patch.object(RefreshToken, "blacklist", blacklist_after_rival_arrives):
        run_in_threads(partial(post, "token-refresh"), partial(post, rival))

    assert sorted(codes) == [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED]
