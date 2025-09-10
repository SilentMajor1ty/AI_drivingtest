from django.urls import path
from . import views

app_name = 'scheduling'

urlpatterns = [
    # Calendar and lessons
    path('calendar/', views.calendar_view, name='calendar'),
    path('api/calendar-lessons/', views.calendar_lessons_api, name='calendar_lessons_api'),
    path('lessons/', views.LessonListView.as_view(), name='lesson_list'),
    path('lessons/create/', views.LessonCreateView.as_view(), name='lesson_create'),
    path('lessons/<int:pk>/', views.LessonDetailView.as_view(), name='lesson_detail'),
    path('lessons/<int:pk>/edit/', views.LessonUpdateView.as_view(), name='lesson_edit'),
    path('lessons/<int:pk>/rate/', views.rate_lesson, name='rate_lesson'),
    path('lessons/<int:lesson_id>/details/', views.lesson_details_ajax, name='lesson_details_ajax'),
    
    # Problem reporting
    path('report-problem/', views.report_problem, name='report_problem'),
    
    # Lesson management
    path('lessons/<int:lesson_id>/reschedule/', views.reschedule_lesson, name='reschedule_lesson'),
    path('lessons/<int:lesson_id>/cancel/', views.cancel_lesson, name='cancel_lesson'),
    
    # Schedule management
    path('schedule/', views.ScheduleView.as_view(), name='schedule'),
    path('teacher-lessons/', views.teacher_lesson_management, name='teacher_lesson_management'),
    path('teacher-schedule/<int:teacher_id>/', views.teacher_schedule, name='teacher_schedule'),
]