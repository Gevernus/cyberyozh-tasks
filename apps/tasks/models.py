from django.conf import settings
from django.db import connections, models, transaction
from django.db.models import Count, F, OuterRef, Subquery
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class StatusTransitionError(Exception):
    """The requested status change does not apply to the task's current state."""


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    class Priority(models.IntegerChoices):
        # Integers keep ordering by priority meaningful (low < medium < high).
        LOW = 1, "Low"
        MEDIUM = 2, "Medium"
        HIGH = 3, "High"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, max_length=10_000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    due_date = models.DateField(null=True, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authored_tasks",
        db_index=False,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        db_index=False,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    # Maintained by Comment. The database default keeps inserts from code that
    # predates the column working.
    comments_count = models.PositiveIntegerField(default=0, db_default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # Cursor order, overall and per assignee or author; the latter two also
            # serve as the foreign key indexes.
            models.Index(fields=["-created_at", "-id"], name="task_newest_first_idx"),
            models.Index(
                fields=["assignee", "-created_at", "-id"], name="task_assignee_newest_idx"
            ),
            models.Index(fields=["author", "-created_at", "-id"], name="task_author_newest_idx"),
            models.Index(fields=["status", "due_date"]),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        # completed_at follows status however it changed: an action, a PATCH, the admin.
        if self.is_completed and self.completed_at is None:
            self.completed_at = timezone.now()
        elif not self.is_completed:
            self.completed_at = None
        update_fields = kwargs.get("update_fields")
        if update_fields is None and not self._state.adding:
            # A full save never writes back a comment counter read earlier.
            update_fields = [
                field.name
                for field in self._meta.concrete_fields
                if not field.primary_key and field.name != "comments_count"
            ]
        if update_fields is not None and "status" in update_fields:
            update_fields = {*update_fields, "completed_at"}
        kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)

    @property
    def is_completed(self) -> bool:
        return self.status == self.Status.DONE

    def complete(self) -> None:
        with transaction.atomic():
            self._refresh_locked()
            if self.is_completed:
                raise StatusTransitionError("Task is already completed.")
            self.status = self.Status.DONE
            self.save(update_fields=["status", "updated_at"])

    def reopen(self) -> None:
        with transaction.atomic():
            self._refresh_locked()
            if not self.is_completed:
                raise StatusTransitionError("Task is not completed.")
            self.status = self.Status.TODO
            self.save(update_fields=["status", "updated_at"])

    def _refresh_locked(self) -> None:
        # The row stays locked until the transaction ends, so concurrent status
        # changes of one task run one after another.
        self.refresh_from_db(from_queryset=Task.objects.select_for_update())


def comments_per_task(comments: models.QuerySet) -> Subquery:
    """How many of ``comments`` belong to the task of the outer query."""
    return Subquery(
        comments.filter(task=OuterRef("pk"))
        .order_by()
        .values("task")
        .annotate(count=Count("pk"))
        .values("count")
    )


DELETE_AND_DECREMENT = """
WITH deleted AS (
    DELETE FROM tasks_comment WHERE id IN ({selected}) RETURNING task_id
), decremented AS (
    UPDATE tasks_task SET comments_count = comments_count - removed.amount
    FROM (SELECT task_id, count(*) AS amount FROM deleted GROUP BY task_id) AS removed
    WHERE tasks_task.id = removed.task_id
)
SELECT count(*) FROM deleted
"""


class CommentQuerySet(models.QuerySet):
    def delete(self):
        connection = connections[self.db]
        if connection.vendor != "postgresql":
            return self._decrement_then_delete()
        selected, params = self.order_by().values("pk").query.get_compiler(self.db).as_sql()
        with connection.cursor() as cursor:
            cursor.execute(DELETE_AND_DECREMENT.format(selected=selected), params)
            (deleted,) = cursor.fetchone()
        return deleted, ({self.model._meta.label: deleted} if deleted else {})

    def _decrement_then_delete(self):
        # SQLite admits one writer at a time, so nothing changes between the two.
        with transaction.atomic(using=self.db):
            Task.objects.using(self.db).filter(pk__in=self.values("task")).update(
                comments_count=F("comments_count") - comments_per_task(self)
            )
            return super().delete()


class Comment(models.Model):
    """A comment on a task.

    Task.comments_count follows comments in the same transaction: +1 on creation,
    minus the rows a DELETE actually removed on deletion, so a comment deleted by
    two requests at once counts once. Deletion never loads comments one by one,
    which is why no delete signal is connected to Comment. bulk_create bypasses
    the counter.
    """

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="comments", db_index=False
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments"
    )
    text = models.TextField(max_length=2_000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CommentQuerySet.as_manager()

    class Meta:
        ordering = ["created_at"]
        indexes = [
            # Cursor order within a task; also serves as the foreign key index.
            models.Index(
                fields=["task", "created_at", "id"], name="comment_task_oldest_first_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"Comment #{self.pk} on task #{self.task_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            super().save(*args, **kwargs)
            return
        with transaction.atomic():
            super().save(*args, **kwargs)
            Task.objects.filter(pk=self.task_id).update(comments_count=F("comments_count") + 1)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            deleted, per_model = super().delete(*args, **kwargs)
            if deleted:
                Task.objects.filter(pk=self.task_id).update(
                    comments_count=F("comments_count") - deleted
                )
        return deleted, per_model


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def _decrement_comments_of_deleted_user(sender, instance, **kwargs) -> None:
    # The cascade deletes the user's comments without Comment.delete(). Their own
    # tasks are skipped: those are deleted too.
    theirs = Comment.objects.filter(author=instance)
    Task.objects.filter(pk__in=theirs.values("task")).exclude(author=instance).update(
        comments_count=F("comments_count") - comments_per_task(theirs)
    )
