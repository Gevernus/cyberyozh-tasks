from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CommentViewSet, TaskViewSet

router = SimpleRouter()
router.register("tasks", TaskViewSet, basename="task")

comment_list = CommentViewSet.as_view({"get": "list", "post": "create"})
comment_detail = CommentViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    *router.urls,
    path("tasks/<int:task_pk>/comments/", comment_list, name="task-comment-list"),
    path("tasks/<int:task_pk>/comments/<int:pk>/", comment_detail, name="task-comment-detail"),
]
