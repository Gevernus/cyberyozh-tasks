from rest_framework.pagination import CursorPagination, PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NewestFirstCursorPagination(CursorPagination):
    """Every page is an index range scan. The id breaks ties between equal timestamps."""

    ordering = ("-created_at", "-id")
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class OldestFirstCursorPagination(NewestFirstCursorPagination):
    ordering = ("created_at", "id")
