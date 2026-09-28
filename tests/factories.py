import factory
from django.contrib.auth import get_user_model

DEFAULT_PASSWORD = "Str0ng-pass-123"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    password = factory.django.Password(DEFAULT_PASSWORD)


class TaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "tasks.Task"

    title = factory.Sequence(lambda n: f"Task {n}")
    description = "Something to do"
    author = factory.SubFactory(UserFactory)


class CommentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "tasks.Comment"

    task = factory.SubFactory(TaskFactory)
    author = factory.SubFactory(UserFactory)
    text = "Looks good"
