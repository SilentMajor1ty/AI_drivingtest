from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.db.models import Count
import logging

from .models import Assignment, AssignmentSubmission, AssignmentTemplate, Notification

logger = logging.getLogger('admin_actions')


class AssignmentSubmissionInline(admin.TabularInline):
    model = AssignmentSubmission
    fields = ('version', 'submission_file', 'comments', 'submitted_at', 'is_final')
    readonly_fields = ('submitted_at', 'version', 'file_size')
    extra = 0
    
    def has_add_permission(self, request, obj=None):
        return False  # Students submit through frontend


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'student', 'lesson_link', 'due_date', 'status',
        'submission_count', 'grade', 'is_overdue_display'
    )
    list_filter = ('status', 'due_date', 'lesson__subject', 'created_at')
    search_fields = (
        'title', 'student__first_name', 'student__last_name',
        'lesson__title', 'lesson__teacher__first_name', 'lesson__teacher__last_name'
    )
    date_hierarchy = 'due_date'
    
    fieldsets = (
        ('Assignment Details', {
            'fields': ('title', 'description', 'lesson', 'student')
        }),
        ('Schedule', {
            'fields': ('due_date', 'status')
        }),
        ('Materials', {
            'fields': ('assignment_file',)
        }),
        ('Teacher Feedback', {
            'fields': ('teacher_comments', 'grade'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at', 'submitted_at', 'reviewed_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ('created_at', 'updated_at', 'submitted_at', 'reviewed_at')
    inlines = [AssignmentSubmissionInline]
    
    def lesson_link(self, obj):
        if obj.lesson:
            url = reverse('admin:scheduling_lesson_change', args=[obj.lesson.pk])
            return format_html('<a href="{}">{}</a>', url, obj.lesson.title)
        return '-'
    lesson_link.short_description = 'Lesson'
    
    def submission_count(self, obj):
        count = obj.submissions.count()
        if count > 0:
            return format_html('<span style="color: green;">{}</span>', count)
        return format_html('<span style="color: red;">0</span>')
    submission_count.short_description = 'Submissions'
    
    def is_overdue_display(self, obj):
        if obj.is_overdue:
            return format_html('<span style="color: red;">OVERDUE</span>')
        return '-'
    is_overdue_display.short_description = 'Status'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        
        action = "updated" if change else "created"
        logger.info(f"User {request.user.username} {action} assignment: {obj.title}")
        
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('lesson', 'student').annotate(
            submission_count=Count('submissions')
        )
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        elif request.user.is_teacher():
            return qs.filter(lesson__teacher=request.user)
        elif request.user.is_student():
            return qs.filter(student=request.user)
        return qs.none()


@admin.register(AssignmentSubmission)
class AssignmentSubmissionAdmin(admin.ModelAdmin):
    list_display = ('assignment', 'version', 'submitted_at', 'file_size_display', 'is_final')
    list_filter = ('submitted_at', 'is_final', 'assignment__lesson__subject')
    search_fields = ('assignment__title', 'assignment__student__first_name', 'assignment__student__last_name')
    date_hierarchy = 'submitted_at'
    
    fieldsets = (
        ('Submission Details', {
            'fields': ('assignment', 'version', 'submission_file')
        }),
        ('Metadata', {
            'fields': ('comments', 'submitted_at', 'file_size', 'is_final')
        })
    )
    
    readonly_fields = ('submitted_at', 'file_size', 'version')
    
    def file_size_display(self, obj):
        if obj.file_size:
            if obj.file_size < 1024 * 1024:  # Less than 1MB
                return f"{obj.file_size / 1024:.1f} KB"
            else:
                return f"{obj.file_size / (1024 * 1024):.1f} MB"
        return '-'
    file_size_display.short_description = 'File Size'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('assignment', 'assignment__student')
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        elif request.user.is_teacher():
            return qs.filter(assignment__lesson__teacher=request.user)
        elif request.user.is_student():
            return qs.filter(assignment__student=request.user)
        return qs.none()


@admin.register(AssignmentTemplate)
class AssignmentTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'default_duration_days', 'created_by', 'created_at')
    list_filter = ('subject', 'created_at')
    search_fields = ('name', 'subject__name')
    
    fieldsets = (
        ('Template Information', {
            'fields': ('name', 'subject')
        }),
        ('Content Template', {
            'fields': ('title_template', 'description_template', 'default_duration_days')
        }),
        ('Materials', {
            'fields': ('template_file',)
        })
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        return qs.none()


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'notification_type', 'is_read', 'sent_at')
    list_filter = ('notification_type', 'is_read', 'sent_at', 'sent_push', 'sent_email')
    search_fields = ('title', 'message', 'user__first_name', 'user__last_name')
    date_hierarchy = 'sent_at'
    
    fieldsets = (
        ('Notification Details', {
            'fields': ('user', 'notification_type', 'title', 'message')
        }),
        ('Related Objects', {
            'fields': ('lesson', 'assignment'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_read', 'read_at', 'sent_push', 'sent_email')
        }),
        ('Timestamps', {
            'fields': ('sent_at',),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ('sent_at', 'read_at')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        else:
            return qs.filter(user=request.user)
