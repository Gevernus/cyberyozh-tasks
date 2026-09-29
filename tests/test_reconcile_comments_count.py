from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.tasks.models import Task
from tests.factories import CommentFactory, TaskFactory

pytestmark = pytest.mark.django_db


def reconcile(*args: str) -> str:
    out = StringIO()
    call_command("reconcile_comments_count", *args, stdout=out)
    return out.getvalue()


def test_corrects_only_the_counters_that_are_off():
    undercounted, overcounted, right = TaskFactory.create_batch(3)
    CommentFactory.create_batch(3, task=undercounted)
    CommentFactory(task=right)
    Task.objects.filter(pk=undercounted.pk).update(comments_count=1)
    Task.objects.filter(pk=overcounted.pk).update(comments_count=2)

    output = reconcile("--batch-size", "2")

    assert "Corrected tasks: 2" in output
    assert dict(Task.objects.values_list("pk", "comments_count")) == {
        undercounted.pk: 3,
        overcounted.pk: 0,
        right.pk: 1,
    }
    assert "Corrected tasks: 0" in reconcile()


def test_rejects_an_empty_batch():
    with pytest.raises(CommandError):
        reconcile("--batch-size", "0")
