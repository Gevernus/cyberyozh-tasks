import datetime

import pytest
from django.urls import reverse

from apps.tasks.models import Task
from tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("task-list")


def result_ids(response) -> set[int]:
    return {item["id"] for item in response.data["results"]}


def test_filter_by_status(auth_client):
    done = TaskFactory(status=Task.Status.DONE)
    TaskFactory(status=Task.Status.TODO)

    response = auth_client.get(LIST_URL, {"status": "done"})

    assert result_ids(response) == {done.pk}


def test_filter_by_assignee_and_unassigned(auth_client, user):
    mine = TaskFactory(assignee=user)
    unassigned = TaskFactory()

    assert result_ids(auth_client.get(LIST_URL, {"assignee": user.pk})) == {mine.pk}
    assert result_ids(auth_client.get(LIST_URL, {"unassigned": "true"})) == {unassigned.pk}


def test_filter_by_author(auth_client, user):
    authored = TaskFactory(author=user)
    TaskFactory()

    assert result_ids(auth_client.get(LIST_URL, {"author": user.pk})) == {authored.pk}


def test_filter_by_priority(auth_client):
    high = TaskFactory(priority=Task.Priority.HIGH)
    TaskFactory(priority=Task.Priority.LOW)

    assert result_ids(auth_client.get(LIST_URL, {"priority": 3})) == {high.pk}


def test_filter_by_due_date_range(auth_client):
    soon = TaskFactory(due_date=datetime.date(2030, 1, 10))
    TaskFactory(due_date=datetime.date(2030, 3, 1))
    TaskFactory(due_date=None)

    response = auth_client.get(LIST_URL, {"due_after": "2030-01-01", "due_before": "2030-01-31"})

    assert result_ids(response) == {soon.pk}


def test_search_in_title_and_description(auth_client):
    by_title = TaskFactory(title="Fix login bug")
    by_description = TaskFactory(title="Misc", description="login page is slow")
    TaskFactory(title="Unrelated")

    response = auth_client.get(LIST_URL, {"search": "login"})

    assert result_ids(response) == {by_title.pk, by_description.pk}


def test_ordering_by_priority(auth_client):
    low = TaskFactory(priority=Task.Priority.LOW)
    high = TaskFactory(priority=Task.Priority.HIGH)
    medium = TaskFactory(priority=Task.Priority.MEDIUM)

    response = auth_client.get(LIST_URL, {"ordering": "-priority"})

    assert [item["id"] for item in response.data["results"]] == [high.pk, medium.pk, low.pk]


def test_invalid_filter_value_returns_400(auth_client):
    assert auth_client.get(LIST_URL, {"status": "bogus"}).status_code == 400
