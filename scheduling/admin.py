from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
import logging

from .models import Subject, Lesson, LessonTemplate, Schedule, ProblemReport, LessonFeedback

logger = logging.getLogger('admin_actions')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'lesson_count')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    
    def lesson_count(self, obj):
        return obj.lessons.count()
    lesson_count.short_description = 'Lessons'


@admin.register(Lesson) 
class LessonAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'teacher', 'student', 'subject', 'start_time_display', 
        'duration_display', 'status', 'teacher_rating', 'student_rating'
    )
    list_filter = ('status', 'subject', 'teacher', 'start_time')
    search_fields = ('title', 'teacher__first_name', 'teacher__last_name', 
                    'student__first_name', 'student__last_name')
    date_hierarchy = 'start_time'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'subject', 'teacher', 'student')
        }),
        ('Schedule', {
            'fields': ('start_time', 'end_time', 'status')
        }),
        ('Content', {
            'fields': ('description', 'materials', 'zoom_link')
        }),
        ('Ratings & Feedback', {
            'fields': ('teacher_rating', 'teacher_comments', 'student_rating', 'student_comments'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def start_time_display(self, obj):
        return obj.start_time.strftime('%Y-%m-%d %H:%M')
    start_time_display.short_description = 'Start Time'
    start_time_display.admin_order_field = 'start_time'
    
    def duration_display(self, obj):
        return f"{obj.duration_minutes} min"
    duration_display.short_description = 'Duration'
    
    def save_model(self, request, obj, form, change):
        if not change:  # Creating new lesson
            obj.created_by = request.user
        
        action = "updated" if change else "created"
        logger.info(f"User {request.user.username} {action} lesson: {obj.title}")
        
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        elif request.user.is_teacher():
            return qs.filter(teacher=request.user)
        elif request.user.is_student():
            return qs.filter(student=request.user)
        return qs.none()


@admin.register(ProblemReport)
class ProblemReportAdmin(admin.ModelAdmin):
    list_display = ('lesson', 'reporter', 'problem_type', 'created_at', 'is_resolved')
    list_filter = ('problem_type', 'is_resolved', 'created_at')
    search_fields = ('lesson__title', 'reporter__first_name', 'reporter__last_name', 'description')
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('Информация о проблеме', {
            'fields': ('lesson', 'reporter', 'problem_type', 'description', 'created_at')
        }),
        ('Решение', {
            'fields': ('is_resolved', 'resolved_at', 'resolved_by'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        return qs.none()


@admin.register(LessonTemplate)
class LessonTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'default_duration_minutes', 'created_by', 'created_at')
    list_filter = ('subject', 'created_at')
    search_fields = ('name', 'subject__name')
    
    fieldsets = (
        ('Template Information', {
            'fields': ('name', 'subject')
        }),
        ('Content Template', {
            'fields': ('title_template', 'description_template', 'default_duration_minutes')
        }),
        ('Materials', {
            'fields': ('materials',)
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


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'day_of_week_display', 'time_slot', 'is_available')
    list_filter = ('day_of_week', 'is_available', 'teacher')
    search_fields = ('teacher__first_name', 'teacher__last_name')
    
    def day_of_week_display(self, obj):
        return obj.get_day_of_week_display()
    day_of_week_display.short_description = 'Day'
    day_of_week_display.admin_order_field = 'day_of_week'
    
    def time_slot(self, obj):
        return f"{obj.start_time.strftime('%H:%M')} - {obj.end_time.strftime('%H:%M')}"
    time_slot.short_description = 'Time Slot'


@admin.register(LessonFeedback)
class LessonFeedbackAdmin(admin.ModelAdmin):
    list_display = ('lesson', 'user', 'is_teacher', 'rating', 'created_at')
    list_filter = ('is_teacher', 'rating', 'created_at', 'lesson__teacher')
    search_fields = ('lesson__title', 'user__first_name', 'user__last_name', 'comment')
    readonly_fields = ('created_at',)
