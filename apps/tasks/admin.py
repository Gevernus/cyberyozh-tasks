from django.contrib import admin

from .models import Comment, Task


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    raw_id_fields = ["author"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "status", "priority", "author", "assignee", "due_date"]
    list_filter = ["status", "priority"]
    search_fields = ["title", "description"]
    raw_id_fields = ["author", "assignee"]
    readonly_fields = ["comments_count", "completed_at", "created_at", "updated_at"]
    list_select_related = ["author", "assignee"]
    inlines = [CommentInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["id", "task", "author", "created_at"]
    search_fields = ["text"]
    raw_id_fields = ["task", "author"]
    list_select_related = ["task", "author"]
