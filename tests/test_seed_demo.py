import pytest
from django.core.management import call_command

from apps.tasks.management.commands.seed_demo import DEMO_PASSWORD
from apps.tasks.models import Comment, Task

pytestmark = pytest.mark.django_db


def test_seed_demo_is_idempotent(django_user_model):
    call_command("seed_demo")
    call_command("seed_demo")

    assert django_user_model.objects.count() == 3
    assert Task.objects.count() == 4
    assert Comment.objects.count() == 4
    assert django_user_model.objects.get(username="alice").check_password(DEMO_PASSWORD)
    assert Task.objects.get(title="Rotate API keys").completed_at is not None
