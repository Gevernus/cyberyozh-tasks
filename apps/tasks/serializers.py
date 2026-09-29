from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import Comment, Task

User = get_user_model()


class AssigneeField(serializers.PrimaryKeyRelatedField):
    """The id of an active user, or null."""

    def __init__(self, **kwargs):
        kwargs.setdefault("queryset", User.objects.filter(is_active=True))
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)


class TaskSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    assignee = UserSerializer(read_only=True)
    assignee_id = AssigneeField(source="assignee", write_only=True, required=False)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "due_date",
            "author",
            "assignee",
            "assignee_id",
            "comments_count",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["completed_at", "created_at", "updated_at"]


class TaskAssignSerializer(serializers.Serializer):
    assignee_id = AssigneeField(help_text="User id, or null to unassign the task.")


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "task", "author", "text", "created_at", "updated_at"]
        read_only_fields = ["task", "created_at", "updated_at"]
