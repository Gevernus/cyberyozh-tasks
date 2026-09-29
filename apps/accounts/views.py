from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt import views as jwt_views

from config.throttling import (
    AuthAccountAddressRateThrottle,
    AuthAccountRateThrottle,
    AuthRateThrottle,
    FailOpenAnonRateThrottle,
)

from .serializers import (
    RegisterSerializer,
    TokenBlacklistSerializer,
    TokenRefreshSerializer,
    UserSerializer,
)

User = get_user_model()


AUTH_THROTTLES = [FailOpenAnonRateThrottle, AuthRateThrottle]


@extend_schema(tags=["auth"], summary="Register a new user")
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = AUTH_THROTTLES


class TokenObtainPairView(jwt_views.TokenObtainPairView):
    # Per IP, per target account from that IP, per target account from all IPs.
    throttle_classes = [*AUTH_THROTTLES, AuthAccountAddressRateThrottle, AuthAccountRateThrottle]

    def check_throttles(self, request) -> None:
        # Stop at the first refusal. DRF counts a request in every limit that lets it
        # through, so an attempt refused for its address would still use up the
        # account's shared budget, and one address could lock the owner out.
        for throttle in self.get_throttles():
            if not throttle.allow_request(request, self):
                self.throttled(request, throttle.wait())


class TokenRefreshView(jwt_views.TokenRefreshView):
    serializer_class = TokenRefreshSerializer
    throttle_classes = AUTH_THROTTLES


@extend_schema(summary="Log out: revoke a refresh token")
class TokenBlacklistView(jwt_views.TokenBlacklistView):
    serializer_class = TokenBlacklistSerializer
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
