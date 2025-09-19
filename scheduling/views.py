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
from datetime import datetime, timedelta, time as dt_time
from django.db.models import Q
from django.conf import settings
from .models import Lesson, Subject, Schedule, ProblemReport, LessonFile
from .forms import LessonForm
from assignments.models import Notification
from .models import LessonFeedback
from django.db.models import Avg, Count
import logging
from accounts.models import User  # добавлен импорт для списка преподавателей
from zoneinfo import ZoneInfo

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
    
    # Calculate the week start (Monday) in user's timezone
    today = timezone.localdate()
    current_monday = today - timedelta(days=today.weekday())
    week_start = current_monday + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    # Build aware datetime window [week_start 00:00, next_day 00:00) in active TZ
    start_dt = timezone.make_aware(datetime.combine(week_start, dt_time.min))
    end_dt_exclusive = timezone.make_aware(datetime.combine(week_end + timedelta(days=1), dt_time.min))

    # Filter lessons for the current week (exclude cancelled)
    base_qs = Lesson.objects.filter(start_time__gte=start_dt, start_time__lt=end_dt_exclusive)
    if user.is_student():
        lessons = base_qs.filter(student=user)
    elif user.is_teacher():
        lessons = base_qs.filter(teacher=user)
    else:  # Methodist
        lessons = base_qs
    lessons = lessons.exclude(status=Lesson.LessonStatus.CANCELLED).select_related('teacher', 'student', 'subject').order_by('start_time')

    # Group lessons by local day
    lessons_by_day = { (week_start + timedelta(days=i)): [] for i in range(7) }
    for lesson in lessons:
        local_date = timezone.localtime(lesson.start_time).date()
        if week_start <= local_date <= week_end:
            lessons_by_day[local_date].append(lesson)

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
    start_date_naive = datetime(year, month, 1)
    start_date = timezone.make_aware(start_date_naive)
    if month == 12:
        end_date_naive = datetime(year + 1, 1, 1)
    else:
        end_date_naive = datetime(year, month + 1, 1)
    end_date = timezone.make_aware(end_date_naive)

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

        # Tabs (upcoming/all)
        tab = self.request.GET.get('tab', 'upcoming')

        # Build base queryset by role
        if user.is_student():
            base_qs = Lesson.objects.filter(student=user)
        elif user.is_teacher():
            base_qs = Lesson.objects.filter(teacher=user)
        else:
            base_qs = Lesson.objects.all()
        base_qs = base_qs.select_related('teacher', 'student', 'subject')

        # Фильтр по преподавателю (только для методиста)
        selected_teacher = None
        teacher_param = (self.request.GET.get('teacher') or '').strip()
        if hasattr(user, 'is_methodist') and user.is_methodist():
            try:
                teacher_id = int(teacher_param) if teacher_param else None
            except (TypeError, ValueError):
                teacher_id = None
            if teacher_id:
                base_qs = base_qs.filter(teacher_id=teacher_id)
                selected_teacher = teacher_id

        # Предстоящие: запланированные и перенесенные
        upcoming_lessons = base_qs.filter(status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.RESCHEDULED]).order_by('start_time')
        # Завершённые/отменённые
        all_lessons = base_qs.filter(status__in=[Lesson.LessonStatus.CANCELLED, Lesson.LessonStatus.COMPLETED]).order_by('-start_time')
        active_lessons = upcoming_lessons if tab == 'upcoming' else all_lessons

        # Weekly block (оставляем как серверную логику, но в шаблоне не отображаем)
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday

        weekly_lessons = Lesson.objects.filter(
            Q(start_time__date__range=[week_start, week_end]) | Q(original_start_time__date__range=[week_start, week_end])
        ).distinct()
        if user.is_student():
            weekly_lessons = weekly_lessons.filter(student=user)
        elif user.is_teacher():
            weekly_lessons = weekly_lessons.filter(teacher=user)
        weekly_lessons = weekly_lessons.select_related('teacher', 'student', 'subject').order_by('start_time')

        # Список преподавателей для фильтра (методист)
        teachers = []
        if hasattr(user, 'is_methodist') and user.is_methodist():
            teachers = User.objects.filter(role=User.UserRole.TEACHER).order_by('last_name', 'first_name')

        context['weekly_lessons'] = weekly_lessons
        context['upcoming_lessons'] = upcoming_lessons
        context['all_lessons'] = all_lessons
        context['active_lessons'] = active_lessons
        context['current_tab'] = tab
        context['teachers'] = teachers
        context['selected_teacher'] = selected_teacher
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
        # Проставим автора создания, если не установлен
        if not self.object.created_by:
            self.object.created_by = self.request.user
            try:
                self.object.save(update_fields=['created_by'])
            except Exception:
                pass

        # Notifications for the base lesson
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

        # Handle weekly recurrence
        created_copies = 0
        skipped = 0
        errors = []
        cleaned = form.cleaned_data
        if cleaned.get('repeat_weekly'):
            weeks = int(cleaned.get('repeat_weeks') or 0)
            base = self.object
            for i in range(1, weeks + 1):
                try:
                    new_start = base.start_time + timedelta(weeks=i)
                    new_end = base.end_time + timedelta(weeks=i)
                    copy = Lesson(
                        title=base.title,
                        subject=base.subject,
                        teacher=base.teacher,
                        student=base.student,
                        start_time=new_start,
                        end_time=new_end,
                        description=base.description,
                        materials=base.materials,
                        teacher_materials=base.teacher_materials,
                        zoom_link=base.zoom_link,
                        status=Lesson.LessonStatus.SCHEDULED,
                        created_by=self.request.user,
                    )
                    # save triggers model.clean for overlaps, duration, etc.
                    copy.save()

                    # Notify participants
                    Notification.objects.create(
                        user=copy.teacher,
                        notification_type=Notification.NotificationType.LESSON_CREATED,
                        title=f"New lesson assigned: {copy.title}",
                        message=f"You have been assigned a new lesson '{copy.title}' with {copy.student.full_name} on {copy.start_time.strftime('%B %d, %Y at %H:%M')}",
                        lesson=copy
                    )
                    Notification.objects.create(
                        user=copy.student,
                        notification_type=Notification.NotificationType.LESSON_CREATED,
                        title=f"New lesson scheduled: {copy.title}",
                        message=f"A new lesson '{copy.title}' has been scheduled with {copy.teacher.full_name} on {copy.start_time.strftime('%B %d, %Y at %H:%M')}",
                        lesson=copy
                    )
                    created_copies += 1
                except Exception as e:
                    skipped += 1
                    errors.append(str(e))
                    continue

        # Success message
        if created_copies or skipped:
            base_msg = f"Создано повторов: {created_copies}."
            if skipped:
                base_msg += f" Пропущено: {skipped} (возможны конфликты времени)."
            messages.success(self.request, f"Lesson '{self.object.title}' created successfully! " + base_msg)
        else:
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
    
    # New: tabs (upcoming/all)
    tab = request.GET.get('tab', 'upcoming')  # upcoming | all

    # Get filter parameters
    status_filter = (request.GET.get('status') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    student_filter = (request.GET.get('student') or '').strip()
    q = (request.GET.get('q') or '').strip()

    # Base queryset
    lessons = Lesson.objects.filter(teacher=request.user).select_related('student', 'subject').order_by('-start_time')
    
    # Apply tab filter first but allow explicit status filter to override
    if tab == 'upcoming':
        if status_filter:
            lessons = lessons.filter(status=status_filter)
        else:
            lessons = lessons.filter(status=Lesson.LessonStatus.SCHEDULED).order_by('start_time')
    else:
        # all: nothing special here
        pass

    # Apply status filter if provided (for 'all' or explicit selection)
    if status_filter and tab != 'upcoming':
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

    # Search by name/title (supports multiple terms)
    if q:
        terms = [t for t in q.split() if t]
        for term in terms:
            lessons = lessons.filter(
                models.Q(student__first_name__icontains=term) |
                models.Q(student__last_name__icontains=term) |
                models.Q(title__icontains=term)
            )

    # Try to cast student filter to int for template comparison
    try:
        current_filters_student_id = int(student_filter) if student_filter else None
    except ValueError:
        current_filters_student_id = None

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
            'q': q,
        },
        'current_filters_student_id': current_filters_student_id,
        'current_tab': tab,
        'today': timezone.now().date(),
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

    # Get this week's lessons in local timezone
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    start_dt = timezone.make_aware(datetime.combine(start_of_week, dt_time.min))
    end_dt_exclusive = timezone.make_aware(datetime.combine(end_of_week + timedelta(days=1), dt_time.min))

    lessons = Lesson.objects.filter(
        teacher=teacher,
        start_time__gte=start_dt,
        start_time__lt=end_dt_exclusive
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
        'id': lesson.id,
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
        'user_is_student': request.user.is_student(),
    }

    # Role-based participant display
    if request.user.is_student():
        data['teacher'] = lesson.teacher.full_name
        # Student sees teacher name, not their own
    elif request.user.is_teacher():
        data['student'] = lesson.student.full_name
        # Teacher sees student name, not их own
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
    """Возвращает ближайший урок (для ученика), который завершён и ещё не оценён.
    Показываем только в течение 1 часа после окончания урока.
    """
    # Автоматически обновляем статусы уроков
    updated = _auto_complete_elapsed_lessons()

    user = request.user
    if not user.is_student():
        return JsonResponse({'pending': False, 'pending_count': 0})

    now = timezone.now()
    one_hour_ago = now - timedelta(hours=1)
    # Получаем завершённые уроки без отзывов, оконце [end_time ∈ (one_hour_ago, now]]
    lessons_qs = (
        Lesson.objects
        .filter(
            student=user,
            status=Lesson.LessonStatus.COMPLETED,
            end_time__lte=now,
            end_time__gt=one_hour_ago
        )
        .exclude(feedbacks__user=user)
        .select_related('teacher')
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
    expires_at = next_lesson.end_time + timedelta(hours=1)

    # Возвращаем pending в течение часа после окончания; без баннера-напоминания
    return JsonResponse({
        'pending': True,
        'pending_count': pending_count,
        'show_banner': True,
        'lesson': {
            'id': next_lesson.id,
            'title': next_lesson.title,
            'teacher': next_lesson.teacher.full_name,
            'ended_at': next_lesson.end_time.isoformat(),
            'expires_at': expires_at.isoformat(),
        },
        'debug': {
            'auto_completed': updated,
            'now': now.isoformat(),
            'user': user.username,
            'lesson_end': next_lesson.end_time.isoformat(),
            'expires_at': expires_at.isoformat(),
        } if settings.DEBUG else None
    })


@login_required
def feedback_submit(request):
    """Принимает отзыв ученика по занятию.
    Поддерживает JSON (application/json) и form-encoded (обычные формы).
    """
    # Log request for diagnostics (do not log raw body to avoid leaking tokens/sensitive data)
    try:
        header_keys = [k for k in request.META.keys() if k.startswith('HTTP_')]
        logger.info(f"feedback_submit request: method={request.method} path={request.path} user={getattr(request.user,'username',None)} content_type={request.META.get('CONTENT_TYPE')} csrf_cookie={bool(request.COOKIES.get('csrftoken'))} csrf_header={request.META.get('HTTP_X_CSRFTOKEN')} headers={header_keys}")
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
        # Для fetch ожидаем JSON, для обычного запроса — редирект
        if request.method == 'POST':
            return JsonResponse({'success': False, 'error': 'Доступ запрещён'}, status=403)
        messages.error(request, 'Доступ запрещён')
        return redirect('scheduling:lesson_detail', pk=lesson_id)

    if request.method == 'POST':
        new_date = request.POST.get('new_start_date')
        new_time = request.POST.get('new_start_time')
        start_iso = request.POST.get('start_time')
        end_iso = request.POST.get('end_time')
        user_timezone = request.POST.get('user_timezone') or 'UTC'
        try:
            # Вычисляем новую дату начала
            if new_date and new_time:
                naive_dt = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
                try:
                    local_start = naive_dt.replace(tzinfo=ZoneInfo(user_timezone))
                except Exception:
                    local_start = timezone.make_aware(naive_dt)
                new_start_utc = local_start.astimezone(ZoneInfo('UTC'))
            elif start_iso:
                naive_dt = datetime.fromisoformat(start_iso)
                try:
                    local_start = naive_dt.replace(tzinfo=ZoneInfo(user_timezone))
                except Exception:
                    local_start = timezone.make_aware(naive_dt)
                new_start_utc = local_start.astimezone(ZoneInfo('UTC'))
            else:
                raise ValueError('Не передана новая дата/время начала')

            # Проверка: нельзя переносить на прошедшее время
            current_time_utc = timezone.now().astimezone(ZoneInfo('UTC'))
            if new_start_utc < current_time_utc:
                error_msg = "Нельзя перенести занятие на прошедшее время (по вашему времени устройства)."
                if request.is_ajax() or request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                messages.error(request, error_msg)
                return redirect('scheduling:lesson_detail', pk=lesson_id)

            # Длительность сохраняем, если новый конец не передан
            if end_iso:
                naive_end = datetime.fromisoformat(end_iso)
                try:
                    local_end = naive_end.replace(tzinfo=ZoneInfo(user_timezone))
                except Exception:
                    local_end = timezone.make_aware(naive_end)
                new_end = local_end.astimezone(ZoneInfo('UTC'))
            else:
                duration = lesson.end_time - lesson.start_time
                new_end = new_start_utc + duration

            # Сохраняем оригинальные времена только один раз
            if not lesson.original_start_time:
                lesson.original_start_time = lesson.start_time
            if not lesson.original_end_time:
                lesson.original_end_time = lesson.end_time

            lesson.start_time = new_start_utc
            lesson.end_time = new_end
            lesson.status = lesson.LessonStatus.RESCHEDULED
            lesson.save()

            # Уведомления (необязательно)
            try:
                Notification.objects.create(
                    user=lesson.teacher,
                    notification_type=Notification.NotificationType.LESSON_UPDATED,
                    title=f"Занятие перенесено: {lesson.title}",
                    message=f"Новое время: {lesson.start_time.strftime('%d.%m.%Y %H:%M')} - {lesson.end_time.strftime('%H:%M')}",
                    lesson=lesson
                )
                Notification.objects.create(
                    user=lesson.student,
                    notification_type=Notification.NotificationType.LESSON_UPDATED,
                    title=f"Занятие перенесено: {lesson.title}",
                    message=f"Новое время: {lesson.start_time.strftime('%d.%m.%Y %H:%M')} - {lesson.end_time.strftime('%H:%M')}",
                    lesson=lesson
                )
            except Exception:
                # Логируем, но не падаем
                logger.exception('Не удалось создать уведомления о переносе')

            return JsonResponse({'success': True})
        except Exception as e:
            logger.exception('Ошибка при переносе занятия')
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    # Не-POST: обычный переход
    return redirect('scheduling:lesson_detail', pk=lesson_id)


@login_required
def cancel_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    if not request.user.is_methodist():
        if request.method == 'POST':
            return JsonResponse({'success': False, 'error': 'Доступ запрещён'}, status=403)
        messages.error(request, 'Доступ запрещён')
        return redirect('scheduling:lesson_detail', pk=lesson_id)

    if request.method == 'POST':
        try:
            lesson.status = lesson.LessonStatus.CANCELLED
            lesson.save()
            # Можно логировать/уведомить
            try:
                Notification.objects.create(
                    user=lesson.teacher,
                    notification_type=Notification.NotificationType.LESSON_UPDATED,
                    title=f"Занятие отменено: {lesson.title}",
                    message=f"Занятие {lesson.title} было отменено методистом.",
                    lesson=lesson
                )
                Notification.objects.create(
                    user=lesson.student,
                    notification_type=Notification.NotificationType.LESSON_UPDATED,
                    title=f"Занятие отменено: {lesson.title}",
                    message=f"Занятие {lesson.title} было отменено методистом.",
                    lesson=lesson
                )
            except Exception:
                logger.exception('Не удалось создать уведомления об отмене')

            return JsonResponse({'success': True})
        except Exception as e:
            logger.exception('Ошибка при отмене занятия')
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    # Для не-POST оставляем текущую логику
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
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    start_dt = timezone.make_aware(datetime.combine(week_start, dt_time.min))
    end_dt_exclusive = timezone.make_aware(datetime.combine(week_end + timedelta(days=1), dt_time.min))
    lessons = Lesson.objects.filter(
        start_time__gte=start_dt,
        start_time__lt=end_dt_exclusive
    ).select_related('teacher', 'student').order_by('start_time')
    return render(request, 'scheduling/methodist_weekly_lessons.html', {'lessons': lessons, 'week_start': week_start, 'week_end': week_end})

