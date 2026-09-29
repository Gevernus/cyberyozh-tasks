from collections.abc import Callable
from functools import cached_property

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .filters import TaskFilter
from .models import Comment, StatusTransitionError, Task
from .permissions import IsAuthorOrReadOnly, IsTaskAuthorOrAssignee
from .serializers import CommentSerializer, TaskAssignSerializer, TaskSerializer


@extend_schema_view(
    list=extend_schema(summary="List tasks"),
    retrieve=extend_schema(summary="Get a task"),
    create=extend_schema(summary="Create a task (the caller becomes its author)"),
    update=extend_schema(summary="Replace a task (author only)"),
    partial_update=extend_schema(summary="Update a task (author only)"),
    destroy=extend_schema(summary="Delete a task (author only)"),
)
class TaskViewSet(viewsets.ModelViewSet):
    """Tasks are visible to every authenticated user; only the author edits them."""

    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, IsAuthorOrReadOnly]
    filterset_class = TaskFilter
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "updated_at", "due_date", "priority", "title"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Task.objects.select_related("author", "assignee")

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @extend_schema(
        summary="Mark a task as completed",
        description="Allowed for the task author and assignee. Sets `completed_at`.",
        request=None,
        responses=TaskSerializer,
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsTaskAuthorOrAssignee],
    )
    def complete(self, request: Request, pk=None) -> Response:
        return self._change_status(Task.complete)

    @extend_schema(
        summary="Reopen a completed task",
        description="Allowed for the task author and assignee. Resets status to `todo`.",
        request=None,
        responses=TaskSerializer,
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsTaskAuthorOrAssignee],
    )
    def reopen(self, request: Request, pk=None) -> Response:
        return self._change_status(Task.reopen)

    @extend_schema(
        summary="Assign a task to a user (author only)",
        description="Pass `assignee_id: null` to unassign the task.",
        request=TaskAssignSerializer,
        responses={status.HTTP_200_OK: TaskSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated, IsAuthorOrReadOnly],
    )
    def assign(self, request: Request, pk=None) -> Response:
        task = self.get_object()
        serializer = TaskAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task.assignee = serializer.validated_data["assignee_id"]
        task.save(update_fields=["assignee", "updated_at"])
        return Response(self.get_serializer(task).data)

    def _change_status(self, transition: Callable[[Task], None]) -> Response:
        task = self.get_object()
        try:
            transition(task)
        except StatusTransitionError as exc:
            raise ValidationError({"status": str(exc)}) from exc
        return Response(self.get_serializer(task).data)


@extend_schema_view(
    list=extend_schema(summary="List comments of a task"),
    retrieve=extend_schema(summary="Get a comment"),
    create=extend_schema(summary="Comment on a task"),
    update=extend_schema(summary="Replace a comment (comment author only)"),
    partial_update=extend_schema(summary="Edit a comment (comment author only)"),
    destroy=extend_schema(summary="Delete a comment (comment author only)"),
)
@extend_schema(tags=["comments"])
class CommentViewSet(viewsets.ModelViewSet):
    """Comments nested under a task: /api/tasks/{task_pk}/comments/."""

    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, IsAuthorOrReadOnly]
    filter_backends = []

    @cached_property
    def task(self) -> Task:
        return get_object_or_404(Task, pk=self.kwargs["task_pk"])

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation, no URL kwargs
            return Comment.objects.none()
        return self.task.comments.select_related("author")

    def perform_create(self, serializer):
        serializer.save(task=self.task, author=self.request.user)
