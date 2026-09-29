from rest_framework.pagination import CursorPagination, PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Page-number pagination that lets clients pick a page size within limits."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NewestFirstCursorPagination(CursorPagination):
    """Cursor pagination, newest first, for tables too large for OFFSET and COUNT(*).

    Every page is an index range scan however deep the client goes. The order is
    fixed: a cursor is only stable over an unchanging, nearly unique key, and the id
    breaks ties between equal timestamps.
    """

    ordering = ("-created_at", "-id")
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
