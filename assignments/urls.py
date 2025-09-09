from django.urls import path
from . import views

app_name = 'assignments'

urlpatterns = [
    # Assignments
    path('', views.AssignmentListView.as_view(), name='assignment_list'),
    path('create/', views.AssignmentCreateView.as_view(), name='assignment_create'),
    path('<int:pk>/', views.AssignmentDetailView.as_view(), name='assignment_detail'),
    path('<int:pk>/submit/', views.submit_assignment, name='submit_assignment'),
    
    # Notifications
    path('notifications/', views.NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
]