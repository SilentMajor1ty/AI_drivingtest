from django.urls import path
from . import views

app_name = 'assignments'

urlpatterns = [
    # Assignments
    path('', views.AssignmentListView.as_view(), name='assignment_list'),
    path('create/', views.AssignmentCreateView.as_view(), name='assignment_create'),
    path('<int:pk>/', views.AssignmentDetailView.as_view(), name='assignment_detail'),
    path('<int:pk>/submit/', views.submit_assignment, name='submit_assignment'),
    path('<int:pk>/grade/', views.grade_assignment, name='grade_assignment'),
    path('<int:pk>/revise/', views.send_for_revision, name='send_for_revision'),
    
    # File management
    path('submissions/<int:submission_id>/upload-files/', views.upload_assignment_files, name='upload_assignment_files'),
    path('files/<int:file_id>/delete/', views.delete_assignment_file, name='delete_assignment_file'),
    
    # Notifications
    path('notifications/', views.NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('api/notifications/', views.get_notifications_api, name='notifications_api'),
    
    # Analytics
    path('analytics/', views.methodist_analytics, name='methodist_analytics'),
]