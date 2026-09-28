import re
from io import StringIO

import pytest
from django.core.management import call_command

from apps.tasks.models import Comment, Task

pytestmark = pytest.mark.django_db


def seed(*args: str) -> str:
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def printed_password(output: str) -> str:
    return re.search(r"^Password: (\S+)$", output, re.MULTILINE).group(1)


@pytest.fixture(autouse=True)
def _no_demo_password_env(monkeypatch):
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)


def test_seed_demo_is_idempotent(django_user_model):
    seed()
    seed()

    assert django_user_model.objects.count() == 3
    assert Task.objects.count() == 4
    assert Comment.objects.count() == 4
    assert Task.objects.get(title="Rotate API keys").completed_at is not None


def test_generates_a_new_password_on_every_run(django_user_model):
    first = printed_password(seed())
    second = printed_password(seed())

    assert first != second
    for user in django_user_model.objects.all():
        assert user.check_password(second)
        assert not user.check_password(first)


def test_uses_the_given_password_without_printing_it(django_user_model):
    output = seed("--password", "Given-pass-42")

    assert "Given-pass-42" not in output
    assert "Password:" not in output
    assert django_user_model.objects.get(username="bob").check_password("Given-pass-42")


def test_reads_the_password_from_the_environment(django_user_model, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "Env-pass-42")

    output = seed()

    assert "Env-pass-42" not in output
    assert django_user_model.objects.get(username="carol").check_password("Env-pass-42")
