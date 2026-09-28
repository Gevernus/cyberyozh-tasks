from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsAuthorOrReadOnly(BasePermission):
    """Any authenticated user may read; only the object's author may change it."""

    message = "Only the author can modify this object."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return obj.author_id == request.user.id


class IsTaskAuthorOrAssignee(BasePermission):
    """Allows changing task completion to its author and its assignee."""

    message = "Only the task author or assignee can change its completion state."

    def has_object_permission(self, request, view, obj) -> bool:
        return request.user.id in (obj.author_id, obj.assignee_id)
