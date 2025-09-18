from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.db import models
from django.db.models import F
import json
import pytz

from .models import User, UserProfile
from .forms import UserCreateForm, UserUpdateForm


@login_required
def dashboard(request):
    """
    Main dashboard view - redirects based on user role
    """
    user = request.user
    
    if user.is_student():
        # Student dashboard - show upcoming lessons (today & tomorrow), nearest first
        from django.utils import timezone
        from datetime import timedelta
        from scheduling.models import Lesson
        from assignments.models import Assignment
        
        now = timezone.now()
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        # Top 3 upcoming lessons (today & tomorrow)
        upcoming_lessons = (
            Lesson.objects
            .filter(
                student=user,
                status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.RESCHEDULED],
                start_time__gte=now,
                start_time__date__lte=tomorrow,
            )
            .select_related('teacher', 'subject')
            .order_by('start_time')[:3]
        )

        # Top 3 active assignments ordered by nearest deadline first
        pending_assignments = Assignment.objects.filter(
            student=user,
            status__in=[Assignment.AssignmentStatus.ASSIGNED, Assignment.AssignmentStatus.IN_PROGRESS]
        ).select_related('lesson').order_by(F('due_date').asc(nulls_last=True), 'id')[:3]

        # Counts for greeting
        today_lessons_count = Lesson.objects.filter(
            student=user,
            status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.RESCHEDULED],
            start_time__date=today
        ).count()
        active_assignments_count = Assignment.objects.filter(
            student=user,
            status__in=[Assignment.AssignmentStatus.ASSIGNED, Assignment.AssignmentStatus.IN_PROGRESS]
        ).count()

        # Timeline for next 7 days
        start_day = today
        end_day = today + timedelta(days=6)
        timeline_qs = (
            Lesson.objects
            .filter(
                student=user,
                status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.RESCHEDULED],
                start_time__date__range=[start_day, end_day]
            )
            .select_related('teacher', 'subject')
            .order_by('start_time')
        )
        # Group by day
        lessons_by_date = {}
        for l in timeline_qs:
            d = timezone.localtime(l.start_time).date()
            lessons_by_date.setdefault(d, []).append(l)
        timeline_days = []
        for i in range(7):
            d = start_day + timedelta(days=i)
            day_lessons = lessons_by_date.get(d, [])
            # Prepare light-weight items for template
            items = [
                {
                    'id': le.id,
                    'title': le.title,
                    'start': timezone.localtime(le.start_time),
                    'end': timezone.localtime(le.end_time),
                    'subject': getattr(le.subject, 'name', ''),
                }
                for le in day_lessons
            ]
            timeline_days.append({'date': d, 'lessons': items})

        context = {
            'upcoming_lessons': upcoming_lessons,
            'pending_assignments': pending_assignments,
            'today_lessons_count': today_lessons_count,
            'active_assignments_count': active_assignments_count,
            'timeline_days': timeline_days,
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
            models.Q(lesson__teacher=user) | models.Q(created_by=user),
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
        
        # Последние 7 проведённых занятий (COMPLETED)
        recent_lessons = (
            Lesson.objects
            .filter(status=Lesson.LessonStatus.COMPLETED)
            .select_related('teacher', 'student', 'subject')
            .order_by('-start_time')[:7]
        )
        completed_lessons_count = Lesson.objects.filter(status=Lesson.LessonStatus.COMPLETED).count()

        context = {
            'total_users': total_users,
            'total_teachers': total_teachers,
            'total_students': total_students,
            'recent_lessons': recent_lessons,
            'completed_lessons_count': completed_lessons_count,
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
        qs = User.objects.select_related('profile').order_by('-created_at')
        # Role filter
        role = (self.request.GET.get('role') or '').strip()
        valid_roles = {choice[0] for choice in User.UserRole.choices}
        if role in valid_roles:
            qs = qs.filter(role=role)
        # Name search (first/last/middle/username)
        q = (self.request.GET.get('q') or '').strip()
        if q:
            terms = [t for t in q.split() if t]
            for term in terms:
                qs = qs.filter(
                    models.Q(first_name__icontains=term) |
                    models.Q(last_name__icontains=term) |
                    models.Q(middle_name__icontains=term) |
                    models.Q(username__icontains=term)
                )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        role = (self.request.GET.get('role') or '').strip()
        q = (self.request.GET.get('q') or '').strip()
        ctx.update({
            'roles': User.UserRole.choices,
            'selected_role': role,
            'q': q,
        })
        return ctx


class UserCreateView(LoginRequiredMixin, MethodistRequiredMixin, CreateView):
    """Create new user - Methodist only"""
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
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


@login_required
@require_POST
def set_timezone(request):
    """Устанавливает таймзону: сохраняет в сессии и (если отличается) обновляет у пользователя."""
    tz_name = None
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body or '{}')
            tz_name = data.get('timezone')
        else:
            tz_name = request.POST.get('timezone')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'error': 'bad_json'}, status=400)

    if not tz_name or tz_name not in pytz.all_timezones:
        return JsonResponse({'status': 'invalid_timezone'}, status=400)

    request.session['detected_timezone'] = tz_name
    updated = False
    if request.user.is_authenticated and getattr(request.user, 'timezone', None) != tz_name:
        request.user.timezone = tz_name
        request.user.save(update_fields=['timezone'])
        updated = True
    return JsonResponse({'status': 'ok', 'timezone': tz_name, 'updated': updated})
