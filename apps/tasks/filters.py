from django_filters import rest_framework as filters

from .models import Task


class TaskFilter(filters.FilterSet):
    due_after = filters.DateFilter(field_name="due_date", lookup_expr="gte")
    due_before = filters.DateFilter(field_name="due_date", lookup_expr="lte")
    unassigned = filters.BooleanFilter(field_name="assignee", lookup_expr="isnull")

    class Meta:
        model = Task
        fields = ["status", "priority", "author", "assignee"]
