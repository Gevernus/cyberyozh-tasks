from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt import views as jwt_views

from config.throttling import (
    AuthAccountRateThrottle,
    AuthRateThrottle,
    FailOpenAnonRateThrottle,
)

from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()


AUTH_THROTTLES = [FailOpenAnonRateThrottle, AuthRateThrottle]


@extend_schema(tags=["auth"], summary="Register a new user")
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = AUTH_THROTTLES


class TokenObtainPairView(jwt_views.TokenObtainPairView):
    # Per IP and per target account: guessing one password from many addresses
    # runs into the second limit.
    throttle_classes = [*AUTH_THROTTLES, AuthAccountRateThrottle]


class TokenRefreshView(jwt_views.TokenRefreshView):
    throttle_classes = AUTH_THROTTLES


@extend_schema(summary="Log out: revoke a refresh token")
class TokenBlacklistView(jwt_views.TokenBlacklistView):
    throttle_classes = AUTH_THROTTLES


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
