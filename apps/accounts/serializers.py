from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.settings import api_settings
from rest_framework_simplejwt import serializers as jwt_serializers
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public user representation, safe to expose to any authenticated user."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Creates an account without revealing whether a username is taken.

    Format errors name the field; a taken username gets one generic error, raised
    only after every other check passed and after hashing the password, so neither
    the body nor the timing tells it apart from other failures.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "first_name", "last_name"]
        read_only_fields = ["id"]
        # The model's UniqueValidator would answer "already exists"; checked in validate().
        extra_kwargs = {"username": {"validators": [User.username_validator]}}

    def validate(self, attrs):
        # Run Django's password validators against an unsaved instance so that
        # similarity checks can compare the password with username/email.
        candidate = User(**{key: value for key, value in attrs.items() if key != "password"})
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        if User.objects.filter(username=attrs["username"]).exists():
            make_password(attrs["password"])  # the same work as creating the account
            raise registration_failed()
        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError as exc:  # a concurrent request took the username
            raise registration_failed() from exc


def registration_failed() -> serializers.ValidationError:
    return serializers.ValidationError(
        {api_settings.NON_FIELD_ERRORS_KEY: ["Registration failed."]}, code="registration_failed"
    )


class SingleUseRefreshMixin:
    def validate(self, attrs):
        # The blacklist check and the blacklisting are separate queries: two concurrent
        # requests with one token both passed the check and both got a new pair. The
        # token's row is locked first, so the second request waits for the first to
        # commit and then finds the token blacklisted (401).
        jti = self.token_class(attrs["refresh"])[jwt_settings.JTI_CLAIM]
        with transaction.atomic():
            OutstandingToken.objects.select_for_update().filter(jti=jti).exists()
            return super().validate(attrs)


class TokenRefreshSerializer(SingleUseRefreshMixin, jwt_serializers.TokenRefreshSerializer):
    pass


class TokenBlacklistSerializer(SingleUseRefreshMixin, jwt_serializers.TokenBlacklistSerializer):
    pass
