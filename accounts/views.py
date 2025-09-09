from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.exceptions import PermissionDenied

from .models import User, UserProfile
from .forms import UserCreateForm, UserUpdateForm


@login_required
def dashboard(request):
    """
    Main dashboard view - redirects based on user role
    """
    user = request.user
    
    if user.is_student():
        # Student dashboard - show upcoming lessons and assignments
        from scheduling.models import Lesson
        from assignments.models import Assignment
        
        upcoming_lessons = Lesson.objects.filter(
            student=user,
            status=Lesson.LessonStatus.SCHEDULED
        ).select_related('teacher', 'subject')[:5]
        
        pending_assignments = Assignment.objects.filter(
            student=user,
            status__in=[Assignment.AssignmentStatus.ASSIGNED, Assignment.AssignmentStatus.IN_PROGRESS]
        ).select_related('lesson')[:5]
        
        context = {
            'upcoming_lessons': upcoming_lessons,
            'pending_assignments': pending_assignments,
        }
        return render(request, 'accounts/student_dashboard.html', context)
    
    elif user.is_teacher():
        # Teacher dashboard - show today's lessons and recent assignments
        from django.utils import timezone
        from datetime import timedelta
        from scheduling.models import Lesson
        from assignments.models import Assignment
        
        today = timezone.now().date()
        
        today_lessons = Lesson.objects.filter(
            teacher=user,
            start_time__date=today,
            status=Lesson.LessonStatus.SCHEDULED
        ).select_related('student', 'subject')
        
        recent_submissions = Assignment.objects.filter(
            lesson__teacher=user,
            status=Assignment.AssignmentStatus.SUBMITTED
        ).select_related('student', 'lesson')[:5]
        
        context = {
            'today_lessons': today_lessons,
            'recent_submissions': recent_submissions,
        }
        return render(request, 'accounts/teacher_dashboard.html', context)
    
    elif user.is_methodist():
        # Methodist dashboard - show overview statistics
        from scheduling.models import Lesson
        from assignments.models import Assignment
        
        total_users = User.objects.count()
        total_teachers = User.objects.filter(role=User.UserRole.TEACHER).count()
        total_students = User.objects.filter(role=User.UserRole.STUDENT).count()
        
        recent_lessons = Lesson.objects.select_related('teacher', 'student', 'subject')[:10]
        
        context = {
            'total_users': total_users,
            'total_teachers': total_teachers,
            'total_students': total_students,
            'recent_lessons': recent_lessons,
        }
        return render(request, 'accounts/methodist_dashboard.html', context)
    
    return render(request, 'accounts/dashboard.html')


@login_required
def profile(request):
    """User profile view"""
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Handle profile updates
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.middle_name = request.POST.get('middle_name', user.middle_name)
        user.email = request.POST.get('email', user.email)
        user.phone = request.POST.get('phone', user.phone)
        user.save()
        
        profile.bio = request.POST.get('bio', profile.bio)
        profile.email_notifications = bool(request.POST.get('email_notifications'))
        profile.push_notifications = bool(request.POST.get('push_notifications'))
        profile.save()
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('accounts:profile')
    
    return render(request, 'accounts/profile.html', {'profile': profile})


class MethodistRequiredMixin(UserPassesTestMixin):
    """Mixin to ensure only Methodist can access certain views"""
    
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_methodist()


class UserListView(LoginRequiredMixin, MethodistRequiredMixin, ListView):
    """List all users - Methodist only"""
    model = User
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 20
    
    def get_queryset(self):
        return User.objects.select_related('profile').order_by('-created_at')


class UserCreateView(LoginRequiredMixin, MethodistRequiredMixin, CreateView):
    """Create new user - Methodist only"""
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
        # Create associated profile
        UserProfile.objects.create(user=self.object)
        
        messages.success(self.request, f'User {self.object.username} created successfully!')
        return response


class UserUpdateView(LoginRequiredMixin, UpdateView):
    """Update user - own profile or Methodist can edit all"""
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    
    def test_func(self):
        user = self.get_object()
        return (
            self.request.user == user or 
            self.request.user.is_methodist() or 
            self.request.user.is_superuser
        )
    
    def dispatch(self, request, *args, **kwargs):
        if not self.test_func():
            raise PermissionDenied("You don't have permission to edit this user.")
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        messages.success(self.request, f'User {self.object.username} updated successfully!')
        return super().form_valid(form)
