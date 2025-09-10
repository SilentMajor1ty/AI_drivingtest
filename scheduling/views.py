from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from datetime import datetime, timedelta

from .models import Lesson, Subject, Schedule, ProblemReport
from .forms import LessonForm
from assignments.models import Notification


@login_required
def calendar_view(request):
    """Calendar view showing lessons for a specific week with navigation"""
    user = request.user
    
    # Get week offset from request (default to current week)
    week_offset = int(request.GET.get('week', 0))
    
    # Calculate the week start (Monday)
    today = timezone.now().date()
    current_monday = today - timedelta(days=today.weekday())
    week_start = current_monday + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    
    # Filter lessons for the current week
    if user.is_student():
        lessons = Lesson.objects.filter(
            student=user,
            start_time__date__range=[week_start, week_end]
        ).select_related('teacher', 'subject').order_by('start_time')
    elif user.is_teacher():
        lessons = Lesson.objects.filter(
            teacher=user,
            start_time__date__range=[week_start, week_end]
        ).select_related('student', 'subject').order_by('start_time')
    else:  # Methodist
        lessons = Lesson.objects.filter(
            start_time__date__range=[week_start, week_end]
        ).select_related('teacher', 'student', 'subject').order_by('start_time')
    
    # Group lessons by day
    lessons_by_day = {}
    for i in range(7):  # Monday to Sunday
        day_date = week_start + timedelta(days=i)
        day_lessons = lessons.filter(start_time__date=day_date)
        lessons_by_day[day_date] = day_lessons
    
    # Calculate week navigation
    prev_week = week_offset - 1
    next_week = week_offset + 1
    
    context = {
        'lessons_by_day': lessons_by_day,
        'week_start': week_start,
        'week_end': week_end,
        'week_offset': week_offset,
        'prev_week': prev_week,
        'next_week': next_week,
        'user': user,
        'is_current_week': week_offset == 0,
        'today': today,
    }
    
    return render(request, 'scheduling/calendar.html', context)


@login_required
def calendar_lessons_api(request):
    """API endpoint for calendar lessons"""
    user = request.user
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Filter lessons for the requested month using timezone-aware dates
    start_date = timezone.make_aware(timezone.datetime(year, month, 1))
    if month == 12:
        end_date = timezone.make_aware(timezone.datetime(year + 1, 1, 1))
    else:
        end_date = timezone.make_aware(timezone.datetime(year, month + 1, 1))
    
    if user.is_student():
        lessons = Lesson.objects.filter(
            student=user,
            start_time__gte=start_date,
            start_time__lt=end_date
        ).select_related('teacher', 'subject')
    elif user.is_teacher():
        lessons = Lesson.objects.filter(
            teacher=user,
            start_time__gte=start_date,
            start_time__lt=end_date
        ).select_related('student', 'subject')
    else:  # Methodist
        lessons = Lesson.objects.filter(
            start_time__gte=start_date,
            start_time__lt=end_date
        ).select_related('teacher', 'student', 'subject')
    
    lessons_data = []
    for lesson in lessons:
        lessons_data.append({
            'id': lesson.id,
            'title': lesson.title,
            'subject': lesson.subject.name,
            'start_time': lesson.start_time.isoformat(),
            'end_time': lesson.end_time.isoformat(),
            'status': lesson.status,
            'status_display': lesson.get_status_display(),
            'teacher': lesson.teacher.full_name,
            'student': lesson.student.full_name,
            'description': lesson.description,
            'zoom_link': lesson.zoom_link,
        })
    
    return JsonResponse({'lessons': lessons_data})


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
    form_class = LessonForm
    template_name = 'scheduling/lesson_form.html'
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
    form_class = LessonForm
    template_name = 'scheduling/lesson_form.html'
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
def teacher_lesson_management(request):
    """Teacher lesson management page with filters - Teachers only"""
    if not request.user.is_teacher():
        messages.error(request, "Access denied. Only teachers can view this page.")
        return redirect('accounts:dashboard')
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    student_filter = request.GET.get('student', '')
    
    # Base queryset
    lessons = Lesson.objects.filter(teacher=request.user).select_related('student', 'subject').order_by('-start_time')
    
    # Apply filters
    if status_filter:
        lessons = lessons.filter(status=status_filter)
    
    if date_from:
        try:
            from_date = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            lessons = lessons.filter(start_time__date__gte=from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            lessons = lessons.filter(start_time__date__lte=to_date)
        except ValueError:
            pass
    
    if student_filter:
        lessons = lessons.filter(student__id=student_filter)
    
    # Get all students for filter dropdown
    from accounts.models import User
    students = User.objects.filter(
        role=User.UserRole.STUDENT,
        student_lessons__teacher=request.user
    ).distinct().order_by('first_name', 'last_name')
    
    context = {
        'lessons': lessons,
        'students': students,
        'status_choices': Lesson.LessonStatus.choices,
        'current_filters': {
            'status': status_filter,
            'date_from': date_from,
            'date_to': date_to,
            'student': student_filter,
        }
    }
    
    return render(request, 'scheduling/teacher_lesson_management.html', context)


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


@login_required
def lesson_details_ajax(request, lesson_id):
    """AJAX endpoint for lesson details"""
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    
    # Check permissions
    if request.user.is_student() and lesson.student != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    elif request.user.is_teacher() and lesson.teacher != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    data = {
        'title': lesson.title,
        'subject': lesson.subject.name,
        'date': lesson.start_time.strftime('%d.%m.%Y'),
        'start_time': lesson.start_time.strftime('%H:%M'),
        'end_time': lesson.end_time.strftime('%H:%M'),
        'status': lesson.get_status_display(),
        'description': lesson.description,
        'zoom_link': lesson.zoom_link,
    }
    
    # Role-based participant display
    if request.user.is_student():
        data['teacher'] = lesson.teacher.full_name
        # Student sees teacher name, not their own
    elif request.user.is_teacher():
        data['student'] = lesson.student.full_name
        # Teacher sees student name, not their own
        # Add teacher materials download if available
        if lesson.teacher_materials:
            data['teacher_materials'] = {
                'url': lesson.teacher_materials.url,
                'name': lesson.teacher_materials.name.split('/')[-1]  # Get filename only
            }
    else:  # Methodist
        data['teacher'] = lesson.teacher.full_name
        data['student'] = lesson.student.full_name
        # Methodist sees both names and duration
        data['duration'] = lesson.duration_minutes
        if lesson.teacher_materials:
            data['teacher_materials'] = {
                'url': lesson.teacher_materials.url,
                'name': lesson.teacher_materials.name.split('/')[-1]
            }
    
    # Add general materials if available
    if lesson.materials:
        data['materials'] = {
            'url': lesson.materials.url,
            'name': lesson.materials.name.split('/')[-1]
        }
    
    return JsonResponse(data)


@login_required
@require_POST
def report_problem(request):
    """Handle problem reporting from students"""
    if not request.user.is_student():
        return JsonResponse({'success': False, 'error': 'Only students can report problems'})
    
    lesson_id = request.POST.get('lesson_id')
    problem_type = request.POST.get('problem_type')
    description = request.POST.get('description')
    
    if not all([lesson_id, problem_type, description]):
        return JsonResponse({'success': False, 'error': 'All fields are required'})
    
    try:
        lesson = Lesson.objects.get(id=lesson_id, student=request.user)
        
        # Create problem report
        problem_report = ProblemReport.objects.create(
            lesson=lesson,
            reporter=request.user,
            problem_type=problem_type,
            description=description
        )
        
        # Notify all methodists
        from accounts.models import User
        methodists = User.objects.filter(role=User.UserRole.METHODIST)
        
        for methodist in methodists:
            Notification.objects.create(
                user=methodist,
                notification_type=Notification.NotificationType.LESSON_CREATED,
                title=f"Сообщение о проблеме в занятии",
                message=f"Ученик {request.user.full_name} сообщил о проблеме в занятии '{lesson.title}': {problem_report.get_problem_type_display()}. Описание: {description}",
                lesson=lesson
            )
        
        return JsonResponse({'success': True})
        
    except Lesson.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Lesson not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
