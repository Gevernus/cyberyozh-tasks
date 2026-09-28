from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt import views as jwt_views

from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()


@extend_schema(tags=["auth"], summary="Register a new user")
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "auth"


# simplejwt views have no throttle scope, so credential guessing would only be
# limited by the generic anonymous rate.
class TokenObtainPairView(jwt_views.TokenObtainPairView):
    throttle_scope = "auth"


class TokenRefreshView(jwt_views.TokenRefreshView):
    throttle_scope = "auth"


@extend_schema(tags=["users"])
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Active users, e.g. to pick a task assignee."""

    queryset = User.objects.filter(is_active=True).order_by("username")
    serializer_class = UserSerializer
    search_fields = ["username", "first_name", "last_name"]
    ordering_fields = ["username", "date_joined"]

    @extend_schema(summary="Current user")
    @action(detail=False, methods=["get"])
    def me(self, request: Request) -> Response:
        return Response(self.get_serializer(request.user).data)
