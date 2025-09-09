from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone

from .models import Lesson, Subject, Schedule
from assignments.models import Notification


@login_required
def calendar_view(request):
    """Calendar view showing lessons based on user role"""
    user = request.user
    
    if user.is_student():
        lessons = Lesson.objects.filter(student=user).select_related('teacher', 'subject')
    elif user.is_teacher():
        lessons = Lesson.objects.filter(teacher=user).select_related('student', 'subject')
    else:  # Methodist
        lessons = Lesson.objects.all().select_related('teacher', 'student', 'subject')
    
    context = {
        'lessons': lessons,
        'user': user,
    }
    
    return render(request, 'scheduling/calendar.html', context)


class LessonListView(LoginRequiredMixin, ListView):
    """List view for lessons based on user role"""
    model = Lesson
    template_name = 'scheduling/lesson_list.html'
    context_object_name = 'lessons'
    paginate_by = 10
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_student():
            return Lesson.objects.filter(student=user).select_related('teacher', 'subject')
        elif user.is_teacher():
            return Lesson.objects.filter(teacher=user).select_related('student', 'subject')
        else:  # Methodist
            return Lesson.objects.all().select_related('teacher', 'student', 'subject')


class LessonDetailView(LoginRequiredMixin, DetailView):
    """Detail view for individual lessons"""
    model = Lesson
    template_name = 'scheduling/lesson_detail.html'
    context_object_name = 'lesson'
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_student():
            return Lesson.objects.filter(student=user)
        elif user.is_teacher():
            return Lesson.objects.filter(teacher=user)
        else:  # Methodist
            return Lesson.objects.all()


class LessonCreateView(LoginRequiredMixin, CreateView):
    """Create new lesson - Methodist only"""
    model = Lesson
    template_name = 'scheduling/lesson_form.html'
    fields = ['title', 'subject', 'teacher', 'student', 'start_time', 'end_time', 'description', 'zoom_link']
    success_url = reverse_lazy('scheduling:lesson_list')
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_methodist():
            messages.error(request, "Only Methodist can create lessons.")
            return redirect('scheduling:lesson_list')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
        # Create notifications for teacher and student
        lesson = self.object
        
        # Notify teacher
        Notification.objects.create(
            user=lesson.teacher,
            notification_type=Notification.NotificationType.LESSON_CREATED,
            title=f"New lesson assigned: {lesson.title}",
            message=f"You have been assigned a new lesson '{lesson.title}' with {lesson.student.full_name} on {lesson.start_time.strftime('%B %d, %Y at %H:%M')}",
            lesson=lesson
        )
        
        # Notify student
        Notification.objects.create(
            user=lesson.student,
            notification_type=Notification.NotificationType.LESSON_CREATED,
            title=f"New lesson scheduled: {lesson.title}",
            message=f"A new lesson '{lesson.title}' has been scheduled with {lesson.teacher.full_name} on {lesson.start_time.strftime('%B %d, %Y at %H:%M')}",
            lesson=lesson
        )
        
        messages.success(self.request, f"Lesson '{lesson.title}' created successfully!")
        return response


class LessonUpdateView(LoginRequiredMixin, UpdateView):
    """Update lesson - Methodist only"""
    model = Lesson
    template_name = 'scheduling/lesson_form.html'
    fields = ['title', 'subject', 'teacher', 'student', 'start_time', 'end_time', 'description', 'zoom_link', 'status']
    success_url = reverse_lazy('scheduling:lesson_list')
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_methodist():
            messages.error(request, "Only Methodist can edit lessons.")
            return redirect('scheduling:lesson_list')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Lesson '{self.object.title}' updated successfully!")
        return response


@login_required
def rate_lesson(request, pk):
    """Rate a lesson after completion"""
    lesson = get_object_or_404(Lesson, pk=pk)
    user = request.user
    
    # Check permissions and if lesson can be rated
    if not (user == lesson.teacher or user == lesson.student):
        messages.error(request, "You don't have permission to rate this lesson.")
        return redirect('scheduling:lesson_detail', pk=pk)
    
    if not lesson.can_be_rated:
        messages.error(request, "This lesson cannot be rated yet.")
        return redirect('scheduling:lesson_detail', pk=pk)
    
    if request.method == 'POST':
        rating = int(request.POST.get('rating', 0))
        comments = request.POST.get('comments', '')
        
        if rating < 1 or rating > 10:
            messages.error(request, "Rating must be between 1 and 10.")
            return redirect('scheduling:lesson_detail', pk=pk)
        
        if user == lesson.teacher:
            lesson.teacher_rating = rating
            lesson.teacher_comments = comments
        else:  # student
            lesson.student_rating = rating
            lesson.student_comments = comments
        
        lesson.save()
        messages.success(request, "Your rating has been saved!")
        return redirect('scheduling:lesson_detail', pk=pk)
    
    return render(request, 'scheduling/rate_lesson.html', {'lesson': lesson})


class ScheduleView(LoginRequiredMixin, ListView):
    """View for managing teacher schedules"""
    model = Schedule
    template_name = 'scheduling/schedule.html'
    context_object_name = 'schedules'
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_teacher():
            return Schedule.objects.filter(teacher=user)
        else:  # Methodist
            return Schedule.objects.all().select_related('teacher')


@login_required
def teacher_schedule(request, teacher_id):
    """View specific teacher's schedule - Methodist only"""
    if not request.user.is_methodist():
        messages.error(request, "Access denied.")
        return redirect('accounts:dashboard')
    
    from accounts.models import User
    teacher = get_object_or_404(User, pk=teacher_id, role=User.UserRole.TEACHER)
    
    # Get this week's lessons
    from datetime import datetime, timedelta
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    lessons = Lesson.objects.filter(
        teacher=teacher,
        start_time__date__gte=start_of_week,
        start_time__date__lte=end_of_week
    ).select_related('student', 'subject').order_by('start_time')
    
    context = {
        'teacher': teacher,
        'lessons': lessons,
        'week_start': start_of_week,
        'week_end': end_of_week,
    }
    
    return render(request, 'scheduling/teacher_schedule.html', context)
