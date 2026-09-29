import contextlib
import threading
from unittest import mock

import pytest
from django.db import connection
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tasks.models import Task
from tests.factories import TaskFactory

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="needs PostgreSQL: SQLite ignores SELECT ... FOR UPDATE",
    ),
    pytest.mark.django_db(transaction=True),
]

# How long the first writer holds its row lock waiting for the second request.
# Without the lock both requests reach the write within milliseconds.
RACE_WINDOW = 2.0


@pytest.mark.parametrize(
    ("action", "initial_status", "final_status"),
    [
        ("complete", Task.Status.TODO, Task.Status.DONE),
        ("reopen", Task.Status.DONE, Task.Status.TODO),
    ],
)
def test_concurrent_status_changes_apply_once(user, action, initial_status, final_status):
    task = TaskFactory(author=user, status=initial_status)
    url = reverse(f"task-{action}", args=[task.pk])
    both_passed_check = threading.Barrier(2, timeout=RACE_WINDOW)
    responses = []
    original_save = Task.save

    def save_after_rival_arrives(self, *args, **kwargs):
        # A request that passed the state check waits here for the other one. With the
        # row lock the rival is still blocked in SELECT ... FOR UPDATE, the wait times
        # out and this request commits; without it both would pass the check and write.
        with contextlib.suppress(threading.BrokenBarrierError):
            both_passed_check.wait()
        original_save(self, *args, **kwargs)

    def request() -> None:
        try:
            client = APIClient()
            client.force_authenticate(user=user)
            responses.append(client.post(url))
        finally:
            connection.close()

    with mock.patch.object(Task, "save", save_after_rival_arrives):
        threads = [threading.Thread(target=request) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert sorted(response.status_code for response in responses) == [
        status.HTTP_200_OK,
        status.HTTP_400_BAD_REQUEST,
    ]
    task.refresh_from_db()
    assert task.status == final_status
    assert (task.completed_at is not None) == task.is_completed


def test_concurrent_comments_are_all_counted(user):
    task = TaskFactory()
    url = reverse("task-comment-list", args=[task.pk])
    writers = 8
    start = threading.Barrier(writers, timeout=RACE_WINDOW)
    codes = []

    def comment() -> None:
        try:
            client = APIClient()
            client.force_authenticate(user=user)
            start.wait()
            codes.append(client.post(url, {"text": "me too"}).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=comment) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert codes == [status.HTTP_201_CREATED] * writers
    task.refresh_from_db()
    assert task.comments_count == writers


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
        try:
            codes.append(APIClient().post(reverse(url_name), {"refresh": refresh}).status_code)
        finally:
            connection.close()

    with mock.patch.object(RefreshToken, "blacklist", blacklist_after_rival_arrives):
        threads = [
            threading.Thread(target=post, args=(url_name,))
            for url_name in ("token-refresh", rival)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert sorted(codes) == [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED]
