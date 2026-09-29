import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.tasks.models import Task
from tests.factories import UserFactory

BEFORE_COUNTER = ("tasks", "0001_initial")
COUNTER = ("tasks", "0002_task_comments_count")


def migrate(target) -> None:
    MigrationExecutor(connection).migrate(target)


@pytest.mark.django_db(transaction=True)
def test_the_comment_counter_migration_runs_again_after_failing_midway():
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("tasks")
    migrate([BEFORE_COUNTER])
    try:
        # The state a failed run leaves: the column is there, the migration is not
        # recorded as applied, the backfill stopped partway.
        models = MigrationExecutor(connection).loader.project_state(COUNTER).apps
        old_task, old_comment = models.get_model("tasks.Task"), models.get_model("tasks.Comment")
        with connection.schema_editor() as editor:
            editor.add_field(old_task, old_task._meta.get_field("comments_count"))
        author = UserFactory()
        busy = old_task.objects.create(title="busy", author_id=author.pk, comments_count=1)
        old_task.objects.create(title="quiet", author_id=author.pk, comments_count=2)
        for _ in range(3):
            old_comment.objects.create(task=busy, author_id=author.pk, text="me too")
    finally:
        migrate(latest)

    assert dict(Task.objects.values_list("title", "comments_count")) == {"busy": 3, "quiet": 0}
