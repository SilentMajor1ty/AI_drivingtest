from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
import json
from datetime import datetime, timedelta
from django.db.models import Q
from django.conf import settings
from .models import Lesson, Subject, Schedule, ProblemReport, LessonFile
from .forms import LessonForm
from assignments.models import Notification
from .models import LessonFeedback
from django.db.models import Avg, Count
import logging

logger = logging.getLogger('admin_actions')


def _auto_complete_elapsed_lessons():
    """Авто-пометка прошедших уроков как COMPLETED если время окончания прошло."""
    from django.utils import timezone as _tz
    from .models import Lesson as _L
    now = _tz.now()
    _L.objects.filter(status__in=[_L.LessonStatus.SCHEDULED, _L.LessonStatus.RESCHEDULED], end_time__lt=now).update(status=_L.LessonStatus.COMPLETED)

@login_required
def calendar_view(request):
    """Calendar view showing lessons for a specific week with navigation"""
    _auto_complete_elapsed_lessons()
    user = request.user
    
    # Get week offset from request (default to current week)
    week_offset = int(request.GET.get('week', 0))
    
    # Calculate the week start (Monday)
    today = timezone.now().date()
    current_monday = today - timedelta(days=today.weekday())
    week_start = current_monday + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    
    # Filter lessons for the current week (exclude cancelled so card disappears)
    base_filter = {
        'start_time__date__range': [week_start, week_end]
    }
    if user.is_student():
        lessons = Lesson.objects.filter(student=user, **base_filter)
    elif user.is_teacher():
        lessons = Lesson.objects.filter(teacher=user, **base_filter)
    else:  # Methodist
        lessons = Lesson.objects.filter(**base_filter)
    lessons = lessons.exclude(status=Lesson.LessonStatus.CANCELLED).select_related('teacher', 'student', 'subject').order_by('start_time')

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
    _auto_complete_elapsed_lessons()
    user = request.user
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))
    
    # Filter lessons for the requested month using timezone-aware dates
    start_date = timezone.make_aware(timezone.datetime(year, month, 1))
    if month == 12:
        end_date = timezone.make_aware(timezone.datetime(year + 1, 1, 1))
    else:
        end_date = timezone.make_aware(timezone.datetime(year, month + 1, 1))
    
    base_qs = Lesson.objects.filter(start_time__gte=start_date, start_time__lt=end_date).exclude(status=Lesson.LessonStatus.CANCELLED)
    if user.is_student():
        lessons = base_qs.filter(student=user).select_related('teacher', 'subject')
    elif user.is_teacher():
        lessons = base_qs.filter(teacher=user).select_related('student', 'subject')
    else:  # Methodist
        lessons = base_qs.select_related('teacher', 'student', 'subject')

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Calculate week range
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday

        # Get weekly lessons
        from django.db.models import Q
        weekly_lessons = Lesson.objects.filter(
            Q(start_time__date__range=[week_start, week_end]) | Q(original_start_time__date__range=[week_start, week_end])
        ).distinct().order_by('start_time')

        # Filter based on user role
        if user.is_student():
            weekly_lessons = weekly_lessons.filter(student=user)
        elif user.is_teacher():
            weekly_lessons = weekly_lessons.filter(teacher=user)

        # Select related fields and order by start time
        weekly_lessons = weekly_lessons.select_related(
            'teacher', 'student', 'subject'
        ).order_by('start_time')

        context['weekly_lessons'] = weekly_lessons
        return context


class LessonDetailView(LoginRequiredMixin, DetailView):
    """Detail view for individual lessons"""
    model = Lesson
    template_name = 'scheduling/lesson_detail.html'
    context_object_name = 'lesson'

    def get_queryset(self):
        user = self.request.user
        base_qs = Lesson.objects.all().select_related('teacher','student','subject')
        if user.is_student():
            return base_qs.filter(student=user)
        if user.is_teacher():
            return base_qs.filter(teacher=user)
        return base_qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Expose flags for template
        lesson = context['lesson']
        context['can_see_teacher_materials'] = (self.request.user.is_methodist() or self.request.user == lesson.teacher)
        return context


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
        self.object = form.save()
        # Notifications only (no multi-file logic)
        Notification.objects.create(
            user=self.object.teacher,
            notification_type=Notification.NotificationType.LESSON_CREATED,
            title=f"New lesson assigned: {self.object.title}",
            message=f"You have been assigned a new lesson '{self.object.title}' with {self.object.student.full_name} on {self.object.start_time.strftime('%B %d, %Y at %H:%M')}",
            lesson=self.object
        )
        Notification.objects.create(
            user=self.object.student,
            notification_type=Notification.NotificationType.LESSON_CREATED,
            title=f"New lesson scheduled: {self.object.title}",
            message=f"A new lesson '{self.object.title}' has been scheduled with {self.object.teacher.full_name} on {self.object.start_time.strftime('%B %d, %Y at %H:%M')}",
            lesson=self.object
        )
        messages.success(self.request, f"Lesson '{self.object.title}' created successfully!")
        return redirect(self.get_success_url())


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
        'status_code': lesson.status,
        'description': lesson.description,
        'zoom_link': lesson.zoom_link,
        'can_be_confirmed': lesson.can_be_confirmed,
        'teacher_confirmed': lesson.teacher_confirmed_completion,
        'student_confirmed': lesson.student_confirmed_completion,
        'is_completed': lesson.status == lesson.LessonStatus.COMPLETED,
        'start_iso': lesson.start_time.isoformat(),
        'end_iso': lesson.end_time.isoformat(),
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


# --- NEW: Feedback API ---
@login_required
def feedback_pending(request):
    """Возвращает ближайший урок (для ученика), который завершён и ещё не оценён."""
    # Автоматически обновляем статусы уроков
    updated = _auto_complete_elapsed_lessons()

    user = request.user
    if not user.is_student():
        return JsonResponse({'pending': False, 'pending_count': 0})

    now = timezone.now()
    # Получаем завершённые уроки без отзывов
    lessons_qs = (
        Lesson.objects
        .filter(
            student=user,
            status=Lesson.LessonStatus.COMPLETED,
            end_time__lt=now
        )
        .exclude(feedbacks__user=user)
        .select_related('teacher')  # Оптимизация запроса
        .order_by('end_time')
    )

    pending_count = lessons_qs.count()
    if pending_count == 0:
        return JsonResponse({
            'pending': False,
            'pending_count': 0,
            'debug': {
                'auto_completed': updated,
                'now': now.isoformat(),
                'user': user.username
            } if settings.DEBUG else None
        })

    next_lesson = lessons_qs.first()
    remind = now >= next_lesson.end_time + timedelta(hours=1)

    # Создаём уведомление если прошёл час
    if remind:
        Notification.objects.get_or_create(
            user=user,
            lesson=next_lesson,
            notification_type=Notification.NotificationType.LESSON_FEEDBACK_REMINDER,
            defaults={
                'title': 'Оцените прошедший урок',
                'message': f"Пожалуйста, оцените занятие '{next_lesson.title}' с преподавателем {next_lesson.teacher.full_name}.",
            }
        )

    return JsonResponse({
        'pending': True,
        'pending_count': pending_count,
        'show_banner': remind,
        'lesson': {
            'id': next_lesson.id,
            'title': next_lesson.title,
            'teacher': next_lesson.teacher.full_name,
            'ended_at': next_lesson.end_time.isoformat(),
        },
        'debug': {
            'auto_completed': updated,
            'now': now.isoformat(),
            'user': user.username,
            'lesson_end': next_lesson.end_time.isoformat()
        } if settings.DEBUG else None
    })


@login_required
def feedback_submit(request):
    """Принимает отзыв ученика по занятию.
    Поддерживает JSON (application/json) и form-encoded (обычные формы).
    """
    # Log request for diagnostics
    try:
        body_preview = request.body.decode('utf-8')[:500] if request.body else ''
        header_keys = [k for k in request.META.keys() if k.startswith('HTTP_')]
        logger.info(f"feedback_submit request: method={request.method} path={request.path} user={getattr(request.user,'username',None)} content_type={request.META.get('CONTENT_TYPE')} csrf_cookie={bool(request.COOKIES.get('csrftoken'))} csrf_header={request.META.get('HTTP_X_CSRFTOKEN')} body_preview={body_preview} headers={header_keys}")
    except Exception:
        logger.exception('Failed to log feedback_submit request')

    # Ответ на preflight (обычно handled by middleware), но безопасно вернуть 200
    if request.method == 'OPTIONS':
        return JsonResponse({}, status=200)

    if request.method != 'POST':
        # В режиме DEBUG возвращаем диагностику для помощи в отладке
        if settings.DEBUG:
            return JsonResponse({
                'error': 'Method not allowed',
                'method': request.method,
                'path': request.path,
            }, status=405)
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Разбор данных: если JSON, парсим тело, иначе берём request.POST
    payload = {}
    content_type = request.META.get('CONTENT_TYPE', '')
    try:
        if content_type.startswith('application/json'):
            payload = json.loads(request.body.decode('utf-8') or '{}')
        else:
            # form-encoded (URLSearchParams) или обычная форма
            payload = request.POST
    except Exception:
        payload = request.POST

    lesson_id = payload.get('lesson_id')
    rating = payload.get('rating')
    comment = payload.get('comment', '')

    if not lesson_id or not rating:
        return JsonResponse({'error': 'lesson_id и rating обязательны'}, status=400)

    try:
        rating = int(rating)
    except Exception:
        return JsonResponse({'error': 'Некорректный рейтинг'}, status=400)

    if rating < 1 or rating > 10:
        return JsonResponse({'error': 'Рейтинг должен быть от 1 до 10'}, status=400)

    lesson = get_object_or_404(Lesson, pk=lesson_id)
    user = request.user

    if not user.is_authenticated or not user.is_student() or lesson.student_id != user.id:
        return JsonResponse({'error': 'Доступ запрещён'}, status=403)

    if lesson.status != Lesson.LessonStatus.COMPLETED or timezone.now() <= lesson.end_time:
        return JsonResponse({'error': 'Урок нельзя оценить сейчас'}, status=400)

    if LessonFeedback.objects.filter(lesson=lesson, user=user).exists():
        return JsonResponse({'error': 'Отзыв уже оставлен'}, status=409)

    LessonFeedback.objects.create(
        lesson=lesson,
        user=user,
        is_teacher=False,
        rating=rating,
        comment=comment or ''
    )

    return JsonResponse({'status': 'ok', 'message': 'Спасибо за отзыв'})


@login_required
def feedback_analytics(request):
    if not request.user.is_methodist():
        messages.error(request, 'Доступ запрещён')
        return redirect('accounts:dashboard')

    overall = LessonFeedback.objects.aggregate(avg=Avg('rating'), total=Count('id'))
    recent = LessonFeedback.objects.select_related('lesson', 'user').order_by('-created_at')[:100]

    per_teacher = (
        LessonFeedback.objects.filter(is_teacher=False)
        .values('lesson__teacher')
        .annotate(avg=Avg('rating'), cnt=Count('id'))
        .order_by('-avg')
    )

    # Map teacher id to name for template convenience
    teacher_names = {}
    from django.contrib.auth import get_user_model
    User = get_user_model()
    teacher_ids = [t['lesson__teacher'] for t in per_teacher if t.get('lesson__teacher')]
    if teacher_ids:
        qs = User.objects.filter(id__in=teacher_ids).values('id', 'first_name', 'last_name')
        for r in qs:
            teacher_names[r['id']] = f"{r['first_name']} {r['last_name']}"

    # Attach teacher display name
    per_teacher_list = []
    for t in per_teacher:
        tid = t.get('lesson__teacher')
        per_teacher_list.append({
            'teacher_id': tid,
            'teacher_name': teacher_names.get(tid, ''),
            'avg': t.get('avg'),
            'cnt': t.get('cnt')
        })

    context = {
        'overall_avg': overall.get('avg'),
        'overall_total': overall.get('total') or 0,
        'recent_feedbacks': recent,
        'per_teacher': per_teacher_list,
    }
    return render(request, 'scheduling/feedback_analytics.html', context)


# --- Stubs for views referenced in urls.py but not yet implemented ---
@login_required
def report_problem(request):
    """Create a ProblemReport via POST or redirect to lesson list."""
    if request.method == 'POST':
        lesson_id = request.POST.get('lesson') or request.POST.get('lesson_id')
        description = request.POST.get('description', '')
        problem_type = request.POST.get('problem_type', ProblemReport.ProblemType.OTHER)
        if lesson_id:
            try:
                lesson = Lesson.objects.get(pk=lesson_id)
                ProblemReport.objects.create(
                    lesson=lesson,
                    reporter=request.user,
                    problem_type=problem_type,
                    description=description
                )
                messages.success(request, 'Отчет о проблеме отправлен.')
            except Lesson.DoesNotExist:
                messages.error(request, 'Урок не найден')
        return redirect('scheduling:lesson_list')
    # For GET just redirect
    return redirect('scheduling:lesson_list')


@login_required
def problem_reports(request):
    """Methodist view for listing problem reports"""
    if not request.user.is_methodist():
        messages.error(request, 'Доступ запрещён')
        return redirect('accounts:dashboard')
    reports = ProblemReport.objects.select_related('lesson', 'reporter').order_by('-created_at')
    return render(request, 'scheduling/problem_reports.html', {'reports': reports})


@login_required
def reschedule_lesson(request, lesson_id):
    """Simple reschedule: accept new start/end via POST and set status to RESCHEDULED."""
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    if not request.user.is_methodist():
        messages.error(request, 'Доступ запрещён')
        return redirect('scheduling:lesson_detail', pk=lesson_id)
    if request.method == 'POST':
        start = request.POST.get('start_time')
        end = request.POST.get('end_time')
        try:
            if start:
                lesson.original_start_time = lesson.start_time
                lesson.start_time = timezone.make_aware(timezone.datetime.fromisoformat(start))
            if end:
                lesson.original_end_time = lesson.end_time
                lesson.end_time = timezone.make_aware(timezone.datetime.fromisoformat(end))
            lesson.status = lesson.LessonStatus.RESCHEDULED
            lesson.save()
            messages.success(request, 'Урок перенесён')
        except Exception as e:
            messages.error(request, f'Ошибка при переносе: {e}')
    return redirect('scheduling:lesson_detail', pk=lesson_id)


@login_required
def cancel_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    if not request.user.is_methodist():
        messages.error(request, 'Доступ запрещён')
        return redirect('scheduling:lesson_detail', pk=lesson_id)
    lesson.status = lesson.LessonStatus.CANCELLED
    lesson.save()
    messages.success(request, 'Урок отменён')
    return redirect('scheduling:lesson_list')


@login_required
def confirm_lesson_completion(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    user = request.user
    if user == lesson.teacher:
        lesson.teacher_confirmed_completion = True
    if user == lesson.student:
        lesson.student_confirmed_completion = True
    if lesson.teacher_confirmed_completion and lesson.student_confirmed_completion:
        lesson.status = lesson.LessonStatus.COMPLETED
        lesson.completion_confirmed_at = timezone.now()
    lesson.save()
    messages.success(request, 'Подтверждение сохранено')
    return redirect('scheduling:lesson_detail', pk=lesson_id)


@login_required
def delete_lesson_file(request, file_id):
    # удаляет файл урока (только Methodist или владелец)
    lf = get_object_or_404(LessonFile, pk=file_id)
    lesson = lf.lesson
    if not (request.user.is_methodist() or request.user == lesson.teacher):
        messages.error(request, 'Доступ запрещён')
        return redirect('scheduling:lesson_detail', pk=lesson.id)
    try:
        lf.file.delete(save=False)
        lf.delete()
        messages.success(request, 'Файл удалён')
    except Exception:
        messages.error(request, 'Ошибка при удалении файла')
    return redirect('scheduling:lesson_detail', pk=lesson.id)


@login_required
def methodist_weekly_lessons(request):
    if not request.user.is_methodist():
        messages.error(request, 'Доступ запрещён')
        return redirect('accounts:dashboard')
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    lessons = Lesson.objects.filter(start_time__date__range=[week_start, week_end]).select_related('teacher', 'student').order_by('start_time')
    return render(request, 'scheduling/methodist_weekly_lessons.html', {'lessons': lessons, 'week_start': week_start, 'week_end': week_end})
