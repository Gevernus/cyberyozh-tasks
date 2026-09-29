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
    """What any authenticated user may see about another."""

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Creates an account without revealing whether a username is taken.

    A taken username gets a generic error, after every other check and after
    hashing the password, so neither the body nor the timing gives it away.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "first_name", "last_name"]
        read_only_fields = ["id"]
        # Without the model's UniqueValidator, which answers "already exists".
        extra_kwargs = {"username": {"validators": [User.username_validator]}}

    def validate(self, attrs):
        # An unsaved user lets the similarity check compare against username and email.
        candidate = User(**{key: value for key, value in attrs.items() if key != "password"})
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        if User.objects.filter(username=attrs["username"]).exists():
            make_password(attrs["password"])
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
        # The token's row stays locked until the blacklisting commits, so a concurrent
        # request with the same token finds it blacklisted.
        jti = self.token_class(attrs["refresh"])[jwt_settings.JTI_CLAIM]
        with transaction.atomic():
            OutstandingToken.objects.select_for_update().filter(jti=jti).exists()
            return super().validate(attrs)


class TokenRefreshSerializer(SingleUseRefreshMixin, jwt_serializers.TokenRefreshSerializer):
    pass


class TokenBlacklistSerializer(SingleUseRefreshMixin, jwt_serializers.TokenBlacklistSerializer):
    pass
