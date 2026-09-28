from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project user model.

    Declared up front (even without extra fields) so the user model can evolve
    later without the painful mid-project swap of ``AUTH_USER_MODEL``.
    """
