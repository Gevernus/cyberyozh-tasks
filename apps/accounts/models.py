from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Declared up front, so fields can be added without swapping AUTH_USER_MODEL."""
