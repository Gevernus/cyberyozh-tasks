from django.conf import settings
from django.db import models, transaction
from django.db.models import F, QuerySet
from django.db.models.signals import post_delete
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
    description = models.TextField(blank=True)
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
    # Maintained by Comment, see there. Stored so that lists need no COUNT per task.
    # The database default lets code deployed before the column existed keep inserting.
    comments_count = models.PositiveIntegerField(default=0, db_default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # The task list: newest first, paginated by cursor. The same order within
            # one assignee or author serves "my tasks" pages without sorting; these
            # also stand in for the plain foreign key indexes.
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
        # Keep completed_at consistent with status no matter how status changed
        # (complete/reopen actions, a PATCH of status, the admin).
        if self.is_completed and self.completed_at is None:
            self.completed_at = timezone.now()
        elif not self.is_completed:
            self.completed_at = None
        update_fields = kwargs.get("update_fields")
        if update_fields is None and not self._state.adding:
            # A full save must not write back a comment counter read earlier: comments
            # added meanwhile would be lost.
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
        # Check the state as committed, holding the row lock until the transaction
        # ends, so concurrent complete/reopen calls on one task run one after another.
        self.refresh_from_db(from_queryset=Task.objects.select_for_update())


class Comment(models.Model):
    """A comment on a task.

    Task.comments_count follows comments with atomic F() updates in the same
    transaction: +1 in save() on creation, -1 in the post_delete handler below, which
    also covers cascades (e.g. deleting a user). bulk_create bypasses both; callers
    must set the counters themselves.
    """

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments"
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["task", "created_at"])]

    def __str__(self) -> str:
        return f"Comment #{self.pk} on task #{self.task_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            super().save(*args, **kwargs)
            return
        with transaction.atomic():
            super().save(*args, **kwargs)
            Task.objects.filter(pk=self.task_id).update(comments_count=F("comments_count") + 1)


@receiver(post_delete, sender=Comment)
def _decrement_comments_count(sender, instance: Comment, origin=None, **kwargs) -> None:
    # Runs inside the deletion's transaction. Nothing to count when the task goes too.
    deleting_tasks = isinstance(origin, Task) or (
        isinstance(origin, QuerySet) and origin.model is Task
    )
    if not deleting_tasks:
        Task.objects.filter(pk=instance.task_id).update(comments_count=F("comments_count") - 1)
