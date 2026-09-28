from django.conf import settings
from django.db import models, transaction
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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="authored_tasks"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Typical list queries: "my open tasks", "tasks I created by status".
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["author", "status"]),
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
        if update_fields is not None and "status" in update_fields:
            kwargs["update_fields"] = {*update_fields, "completed_at"}
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
