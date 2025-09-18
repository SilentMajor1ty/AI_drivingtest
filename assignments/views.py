from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, DetailView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db import models
import datetime
from django.utils.text import get_valid_filename
import os
import mimetypes

from .models import Assignment, AssignmentSubmission, Notification
from .forms import AssignmentForm, AssignmentSubmissionForm


# Allowed file extensions and mime types (can be extended or moved to settings)
ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.jpg', '.jpeg', '.png', '.zip'}
ALLOWED_MIME_PREFIXES = {'image/', 'application/', 'text/'}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB

# Helper to validate uploaded file
def is_allowed_file(f):
    # Size
    try:
        if f.size > MAX_FILE_SIZE:
            return False, 'file_too_large'
    except Exception:
        return False, 'unknown_size'
    # Extension
    name = getattr(f, 'name', '')
    _, ext = os.path.splitext(name.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return False, 'bad_extension'
    # MIME type check (best-effort)
    ctype = getattr(f, 'content_type', '')
    if ctype:
        for p in ALLOWED_MIME_PREFIXES:
            if ctype.startswith(p):
                return True, None
        return False, 'bad_mime'
    # Fallback: allow if extension OK
    return True, None

# Helper to produce safe stored filename
def safe_filename(original_name):
    # keep only basename and make valid
    base = os.path.basename(original_name)
    return get_valid_filename(base)


class AssignmentListView(LoginRequiredMixin, ListView):
    """List assignments based on user role"""
    model = Assignment
    template_name = 'assignments/assignment_list.html'
    context_object_name = 'assignments'
    paginate_by = 10
    
    def get_queryset(self):
        user = self.request.user
        status_filter = self.request.GET.get('status', 'all')
        
        # Base queryset based on user role
        if user.is_student():
            queryset = Assignment.objects.filter(student=user).select_related('lesson', 'lesson__subject', 'created_by')
        elif user.is_teacher():
            # Teachers see assignments for their lessons OR assignments they created
            queryset = Assignment.objects.filter(
                models.Q(lesson__teacher=user) | models.Q(created_by=user)
            ).select_related('student', 'lesson', 'lesson__subject', 'created_by')
        else:  # Methodist
            queryset = Assignment.objects.all().select_related('student', 'lesson', 'lesson__subject', 'created_by')
        
        # Apply status filtering
        if status_filter == 'overdue':
            queryset = queryset.filter(
                due_date__lt=timezone.now(),
                status__in=[Assignment.AssignmentStatus.ASSIGNED, Assignment.AssignmentStatus.IN_PROGRESS, Assignment.AssignmentStatus.NEEDS_REVISION]
            )
        elif status_filter == 'submitted':
            queryset = queryset.filter(status__in=[Assignment.AssignmentStatus.SUBMITTED, Assignment.AssignmentStatus.REVIEWED])
        else:
            # Default ('Предстоящие'): exclude submitted/reviewed/completed and order by nearest deadline first
            queryset = queryset.exclude(
                status__in=[
                    Assignment.AssignmentStatus.SUBMITTED,
                    Assignment.AssignmentStatus.REVIEWED,
                    Assignment.AssignmentStatus.COMPLETED,
                ]
            ).order_by('due_date')

        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_filter'] = self.request.GET.get('status', 'all')
        
        # Add filter counts for the template
        user = self.request.user
        if user.is_student():
            base_queryset = Assignment.objects.filter(student=user)
        elif user.is_teacher():
            base_queryset = Assignment.objects.filter(
                models.Q(lesson__teacher=user) | models.Q(created_by=user)
            )
        else:  # Methodist
            base_queryset = Assignment.objects.all()
        
        context['filter_counts'] = {
            # 'Предстоящие' count excludes submitted/reviewed/completed
            'all': base_queryset.exclude(
                status__in=[
                    Assignment.AssignmentStatus.SUBMITTED,
                    Assignment.AssignmentStatus.REVIEWED,
                    Assignment.AssignmentStatus.COMPLETED,
                ]
            ).count(),
            'overdue': base_queryset.filter(
                due_date__lt=timezone.now(),
                status__in=[Assignment.AssignmentStatus.ASSIGNED, Assignment.AssignmentStatus.IN_PROGRESS, Assignment.AssignmentStatus.NEEDS_REVISION]
            ).count(),
            'submitted': base_queryset.filter(status__in=[Assignment.AssignmentStatus.SUBMITTED, Assignment.AssignmentStatus.REVIEWED]).count(),
        }
        
        return context


class AssignmentDetailView(LoginRequiredMixin, DetailView):
    """Detail view for assignments"""
    model = Assignment
    template_name = 'assignments/assignment_detail.html'
    context_object_name = 'assignment'
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_student():
            return Assignment.objects.filter(student=user)
        elif user.is_teacher():
            # Teachers can view assignments for their lessons OR assignments they created
            return Assignment.objects.filter(
                models.Q(lesson__teacher=user) | models.Q(created_by=user)
            )
        else:  # Methodist
            return Assignment.objects.all()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Показываем только реальные submissions студентов (is_final=True)
        context['submissions'] = self.object.submissions.filter(is_final=True).order_by('-submitted_at')

        # Get assignment materials from non-final submissions (uploaded during assignment creation)
        assignment_materials = self.object.submissions.filter(is_final=False).first()
        context['assignment_materials'] = assignment_materials
        
        # Get all assignment files from materials submission
        if assignment_materials:
            context['assignment_files'] = assignment_materials.files.all()
        else:
            context['assignment_files'] = []

        return context


class AssignmentCreateView(LoginRequiredMixin, CreateView):
    """Create new assignment - Methodist and Teachers"""
    model = Assignment
    form_class = AssignmentForm
    template_name = 'assignments/assignment_form.html'
    success_url = reverse_lazy('assignments:assignment_list')
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_student():
            messages.error(request, "Students cannot create assignments.")
            return redirect('assignments:assignment_list')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        print(f"DEBUG: request.FILES = {dict(self.request.FILES)}")  # Показываем все файлы в запросе
        print(f"DEBUG: request.POST = {dict(self.request.POST)}")    # Показываем все POST данные

        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
        # Handle multiple file uploads
        assignment_files = self.request.FILES.getlist('assignment_files')
        print(f"DEBUG: Получено файлов assignment_files: {len(assignment_files)}")  # Отладочный вывод

        if assignment_files:
            from .models import AssignmentSubmission, AssignmentFile
            
            # Validate files first
            validated = []
            for file in assignment_files:
                ok, reason = is_allowed_file(file)
                if not ok:
                    # Skip invalid files and log
                    logger = logging.getLogger('admin_actions')
                    logger.warning(f"Rejected assignment file upload: {file.name}, reason={reason}")
                    continue
                # sanitize filename
                file.name = safe_filename(file.name)
                validated.append(file)

            if validated:
                # Create a default submission for the assignment materials
                submission = AssignmentSubmission.objects.create(
                    assignment=self.object,
                    comments="Assignment materials",
                    is_final=False  # This is not a student submission
                )
                print(f"DEBUG: Создан submission {submission.id}")  # Отладочный вывод

                # Add all uploaded files
                for file in validated:
                    assignment_file = AssignmentFile.objects.create(
                        submission=submission,
                        file=file,
                        original_name=file.name
                    )
                    print(f"DEBUG: Создан файл {assignment_file.original_name}")  # Отладочный вывод

        # Create notification for student
        assignment = self.object
        Notification.objects.create(
            user=assignment.student,
            notification_type=Notification.NotificationType.ASSIGNMENT_ASSIGNED,
            title=f"New assignment: {assignment.title}",
            message=f"You have been assigned a new homework: '{assignment.title}'. Due date: {assignment.due_date.strftime('%B %d, %Y')}",
            assignment=assignment
        )
        
        messages.success(self.request, f"Assignment '{assignment.title}' created successfully!")
        return response


@login_required
def submit_assignment(request, pk):
    """Submit assignment - Students only"""
    assignment = get_object_or_404(Assignment, pk=pk)
    
    if request.user != assignment.student:
        messages.error(request, "You can only submit your own assignments.")
        return redirect('assignments:assignment_detail', pk=pk)
    
    if request.method == 'POST':
        submission_files = request.FILES.getlist('submission_files')
        comments = request.POST.get('comments', '')
        
        # Either files or comments must be provided
        if not submission_files and not comments.strip():
            messages.error(request, "Please provide either files or comments for your submission.")
            return redirect('assignments:assignment_detail', pk=pk)

        # Validate files (explicit size check)
        validated_files = []
        oversize_files = []
        for file in submission_files:
            if hasattr(file, 'size') and file.size > MAX_FILE_SIZE:
                oversize_files.append(file.name)
                continue
            ok, reason = is_allowed_file(file)
            if not ok:
                messages.error(request, f"Недопустимый файл: {file.name} ({reason})")
                return redirect('assignments:assignment_detail', pk=pk)
            file.name = safe_filename(file.name)
            validated_files.append(file)
        if oversize_files:
            messages.error(request, f"Файл(ы) слишком большие: {', '.join(oversize_files)}. Максимальный размер — 200MB.")
            return redirect('assignments:assignment_detail', pk=pk)

        # Create submission
        submission = AssignmentSubmission.objects.create(
            assignment=assignment,
            comments=comments
        )
        
        # Handle multiple files
        if validated_files:
            from .models import AssignmentFile
            for file in validated_files:
                AssignmentFile.objects.create(
                    submission=submission,
                    file=file,
                    original_name=file.name
                )
        
        # Create notification for teacher (if lesson has a teacher)
        if assignment.lesson and assignment.lesson.teacher:
            Notification.objects.create(
                user=assignment.lesson.teacher,
                notification_type=Notification.NotificationType.ASSIGNMENT_SUBMITTED,
                title=f"Assignment submitted: {assignment.title}",
                message=f"{assignment.student.full_name} has submitted the assignment '{assignment.title}'",
                assignment=assignment
            )
        elif assignment.created_by:
            # If no lesson teacher, notify the person who created the assignment
            Notification.objects.create(
                user=assignment.created_by,
                notification_type=Notification.NotificationType.ASSIGNMENT_SUBMITTED,
                title=f"Assignment submitted: {assignment.title}",
                message=f"{assignment.student.full_name} has submitted the assignment '{assignment.title}'",
                assignment=assignment
            )
        
        messages.success(request, "Assignment submitted successfully!")
        return redirect('assignments:assignment_detail', pk=pk)
    
    return render(request, 'assignments/submit_assignment.html', {'assignment': assignment})


@login_required
def upload_assignment_files(request, submission_id):
    """Upload additional files to assignment submission"""
    from .models import AssignmentFile

    submission = get_object_or_404(AssignmentSubmission, pk=submission_id)

    if request.user != submission.assignment.student:
        return JsonResponse({'success': False, 'error': 'Permission denied'})

    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('files')

        # Validate file sizes (200MB limit per file)
        max_size = MAX_FILE_SIZE
        created = []
        for file in uploaded_files:
            ok, reason = is_allowed_file(file)
            if not ok:
                return JsonResponse({'success': False, 'error': f'Invalid file: {file.name} ({reason})'})
            file.name = safe_filename(file.name)
            af = AssignmentFile.objects.create(submission=submission, file=file, original_name=file.name)
            created.append(af.id)

        return JsonResponse({'success': True, 'created': created})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


class NotificationListView(LoginRequiredMixin, ListView):
    """List user notifications"""
    model = Notification
    template_name = 'assignments/notification_list.html'
    context_object_name = 'notifications'
    paginate_by = 20
    
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by('-sent_at')


@login_required
def mark_notification_read(request, pk):
    """Mark notification as read"""
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.mark_as_read()
    
    return JsonResponse({'status': 'success'})


@login_required
def mark_all_notifications_read(request):
    """Mark all notifications as read for the current user"""
    if request.method == 'POST':
        notifications = Notification.objects.filter(user=request.user, is_read=False)
        notifications.update(is_read=True, read_at=timezone.now())
        return JsonResponse({'status': 'success', 'count': notifications.count()})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def grade_assignment(request, pk):
    """Grade assignment - Teachers only"""
    assignment = get_object_or_404(Assignment, pk=pk)
    
    # Only teachers or methodists can grade assignments
    if not (request.user.is_teacher() or request.user.is_methodist()):
        messages.error(request, "Only teachers and methodists can grade assignments.")
        return redirect('assignments:assignment_detail', pk=pk)
    
    # If assignment has a lesson, only that lesson's teacher can grade it
    # Otherwise, any teacher or methodist can grade it
    if assignment.lesson and assignment.lesson.teacher != request.user and not request.user.is_methodist():
        messages.error(request, "You can only grade assignments for your own students.")
        return redirect('assignments:assignment_detail', pk=pk)
    
    if request.method == 'POST':
        grade = request.POST.get('grade')
        teacher_comments = request.POST.get('teacher_comments', '')
        
        if not grade:
            messages.error(request, "Please select a grade.")
            return redirect('assignments:assignment_detail', pk=pk)
        
        try:
            grade = int(grade)
            if grade < 1 or grade > 10:
                raise ValueError("Grade must be between 1 and 10")
        except ValueError:
            messages.error(request, "Please enter a valid grade (1-10).")
            return redirect('assignments:assignment_detail', pk=pk)
        
        # Update assignment
        assignment.mark_reviewed(teacher_comments, grade)
        
        # Create notification for student
        Notification.objects.create(
            user=assignment.student,
            notification_type=Notification.NotificationType.ASSIGNMENT_REVIEWED,
            title=f"Задание оценено: {assignment.title}",
            message=f"Ваше задание '{assignment.title}' проверено и оценено. Оценка: {grade}/10",
            assignment=assignment
        )
        
        messages.success(request, f"Assignment graded successfully! Grade: {grade}/10")
        return redirect('assignments:assignment_detail', pk=pk)
    
    return redirect('assignments:assignment_detail', pk=pk)


@login_required
def get_notifications_api(request):
    """API endpoint to get user notifications (отдаём UTC и epoch, форматирование на клиенте)."""
    notifications = Notification.objects.filter(user=request.user).order_by('-sent_at')
    unread_count = notifications.filter(is_read=False).count()
    notifications_limited = notifications[:10]

    data = {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'sent_at_utc': n.sent_at.astimezone(datetime.timezone.utc).isoformat().replace('+00:00','Z'),
                'sent_at_epoch': int(n.sent_at.timestamp()),
                'notification_type': n.notification_type,
            }
            for n in notifications_limited
        ],
        'unread_count': unread_count
    }
    return JsonResponse(data)


@login_required
def send_for_revision(request, pk):
    """Send assignment for revision - Teachers and Methodists only"""
    assignment = get_object_or_404(Assignment, pk=pk)
    
    # Only teachers or methodists can send for revision
    if not (request.user.is_teacher() or request.user.is_methodist()):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    # If assignment has a lesson, only that lesson's teacher can send for revision
    if assignment.lesson and assignment.lesson.teacher != request.user and not request.user.is_methodist():
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    if request.method == 'POST':
        revision_comments = request.POST.get('revision_comments', '')
        
        # Send assignment for revision
        assignment.send_for_revision(revision_comments)
        
        # Create notification for student
        Notification.objects.create(
            user=assignment.student,
            notification_type=Notification.NotificationType.ASSIGNMENT_REVIEWED,
            title=f"Требуется доработка: {assignment.title}",
            message=f"Ваше задание '{assignment.title}' требует доработки. Комментарии: {revision_comments}",
            assignment=assignment
        )
        
        messages.success(request, "Assignment sent for revision.")
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def delete_assignment_file(request, file_id):
    """Delete an AssignmentFile. Allowed: submission owner (student), lesson teacher, or methodist.
    If called via AJAX/Fetch, returns JSON; otherwise redirects back to assignment detail.
    """
    from .models import AssignmentFile

    af = get_object_or_404(AssignmentFile, pk=file_id)
    assignment = af.submission.assignment
    user = request.user

    # Permission checks
    allowed = False
    try:
        if user.is_methodist():
            allowed = True
        elif user == assignment.student:
            allowed = True
        elif assignment.lesson and hasattr(user, 'is_teacher') and user.is_teacher() and assignment.lesson.teacher_id == user.id:
            allowed = True
    except Exception:
        allowed = False

    if not allowed:
        if request.method == 'POST' and (request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_ACCEPT','').startswith('application/json')):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
        messages.error(request, 'Доступ запрещён')
        return redirect('assignments:assignment_detail', pk=assignment.pk)

    if request.method == 'POST':
        try:
            # delete file from storage and DB
            af.file.delete(save=False)
            af.delete()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_ACCEPT','').startswith('application/json'):
                return JsonResponse({'success': True})
            messages.success(request, 'Файл удалён')
        except Exception as e:
            logger.exception('Error deleting assignment file')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_ACCEPT','').startswith('application/json'):
                return JsonResponse({'success': False, 'error': str(e)}, status=500)
            messages.error(request, 'Ошибка при удалении файла')
        return redirect('assignments:assignment_detail', pk=assignment.pk)

    # For non-POST requests, redirect back
    return redirect('assignments:assignment_detail', pk=assignment.pk)


@login_required
def methodist_analytics(request):
    """Analytics dashboard for methodist"""
    if not request.user.is_methodist():
        messages.error(request, "Access denied. Only methodists can view analytics.")
        return redirect('accounts:dashboard')
    
    from django.db.models import Avg, Count
    from scheduling.models import Lesson, LessonFeedback
    from accounts.models import User
    from django.utils import timezone as _tz
    from datetime import timedelta as _td, date as _date

    # Parse interval and reference date
    interval = request.GET.get('interval', 'week')  # 'week' | 'month'
    ref_str = request.GET.get('ref')  # YYYY-MM-DD
    try:
        if ref_str:
            parts = [int(p) for p in ref_str.split('-')]
            ref_date = _date(parts[0], parts[1], parts[2])
        else:
            ref_date = _tz.now().date()
    except Exception:
        ref_date = _tz.now().date()

    # Determine period start/end based on interval
    if interval == 'month':
        period_start = ref_date.replace(day=1)
        # first day of next month
        if period_start.month == 12:
            next_month_first = _date(period_start.year + 1, 1, 1)
        else:
            next_month_first = _date(period_start.year, period_start.month + 1, 1)
        period_end = next_month_first - _td(days=1)
    else:
        interval = 'week'
        period_start = ref_date - _td(days=ref_date.weekday())  # Monday
        period_end = period_start + _td(days=6)  # Sunday

    # Navigation refs (previous/next period)
    prev_ref = (period_start - _td(days=1)).isoformat()
    next_ref = (period_end + _td(days=1)).isoformat()
    current_ref = ref_date.isoformat()

    # Grade statistics
    graded_assignments = Assignment.objects.filter(grade__isnull=False)
    
    # Average grade by student
    student_grades = graded_assignments.values(
        'student__id', 'student__first_name', 'student__last_name'
    ).annotate(
        avg_grade=Avg('grade'),
        assignment_count=Count('id')
    ).order_by('-avg_grade')

    # Overall statistics
    total_assignments = Assignment.objects.count()
    completed_assignments = graded_assignments.count()
    avg_grade = graded_assignments.aggregate(avg=Avg('grade'))['avg']

    # Lesson statistics
    total_lessons = Lesson.objects.count()
    completed_lessons = Lesson.objects.filter(status=Lesson.LessonStatus.COMPLETED).count()
    cancelled_lessons = Lesson.objects.filter(status=Lesson.LessonStatus.CANCELLED).count()

    # Average lesson ratings (старые поля в Lesson)
    lesson_ratings = Lesson.objects.filter(
        status=Lesson.LessonStatus.COMPLETED,
        teacher_rating__isnull=False,
        student_rating__isnull=False
    ).aggregate(
        avg_teacher_rating=Avg('teacher_rating'),
        avg_student_rating=Avg('student_rating')
    )

    # Attendance rate (оставлено для совместимости, не выводим)
    scheduled_lessons = Lesson.objects.filter(
        status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.COMPLETED]
    ).count()
    attendance_rate = (completed_lessons / scheduled_lessons * 100) if scheduled_lessons > 0 else 0

    # --- Period completed lessons per teacher (week or month) ---
    period_qs = (
        Lesson.objects
        .filter(status=Lesson.LessonStatus.COMPLETED, start_time__date__range=[period_start, period_end])
        .values('teacher')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')
    )
    teacher_ids = [r['teacher'] for r in period_qs if r.get('teacher')]
    teacher_map = {}
    if teacher_ids:
        for r in User.objects.filter(id__in=teacher_ids).values('id', 'first_name', 'last_name'):
            teacher_map[r['id']] = f"{r['first_name']} {r['last_name']}".strip()
    period_teacher_counts = [
        {
            'teacher_id': row.get('teacher'),
            'teacher_name': teacher_map.get(row.get('teacher'), ''),
            'count': row.get('cnt', 0)
        }
        for row in period_qs
    ]

    # --- Feedback analytics (LessonFeedback) ---
    overall_total = LessonFeedback.objects.count()
    recent_feedbacks = (
        LessonFeedback.objects
        .select_related('lesson', 'lesson__teacher', 'user')
        .order_by('-created_at')[:20]
    )
    per_teacher = (
        LessonFeedback.objects.filter(is_teacher=False)
        .values('lesson__teacher')
        .annotate(avg=Avg('rating'), cnt=Count('id'))
        .order_by('-avg')
    )
    # Resolve teacher names
    teacher_names = {}
    teacher_ids2 = [t['lesson__teacher'] for t in per_teacher if t.get('lesson__teacher')]
    if teacher_ids2:
        qs = User.objects.filter(id__in=teacher_ids2).values('id', 'first_name', 'last_name')
        for r in qs:
            teacher_names[r['id']] = f"{r['first_name']} {r['last_name']}"
    per_teacher_list = [
        {
            'teacher_id': t.get('lesson__teacher'),
            'teacher_name': teacher_names.get(t.get('lesson__teacher'), ''),
            'avg': t.get('avg'),
            'cnt': t.get('cnt'),
        }
        for t in per_teacher
    ]
    
    context = {
        'student_grades': student_grades[:10],  # Top 10 students
        'total_assignments': total_assignments,
        'completed_assignments': completed_assignments,
        'avg_grade': avg_grade,
        'total_lessons': total_lessons,
        'completed_lessons': completed_lessons,
        'cancelled_lessons': cancelled_lessons,
        'attendance_rate': attendance_rate,
        'avg_teacher_rating': lesson_ratings['avg_teacher_rating'],
        'avg_student_rating': lesson_ratings['avg_student_rating'],
        # Period per teacher
        'period_teacher_counts': period_teacher_counts,
        'period_start': period_start,
        'period_end': period_end,
        'interval': interval,
        'prev_ref': prev_ref,
        'next_ref': next_ref,
        'current_ref': current_ref,
        # Feedback additions
        'overall_total': overall_total,
        'recent_feedbacks': recent_feedbacks,
        'per_teacher': per_teacher_list,
    }
    
    return render(request, 'assignments/methodist_analytics.html', context)


@login_required
def teacher_feedback_list(request, teacher_id):
    """Список всех отзывов по выбранному преподавателю (методист)."""
    if not request.user.is_methodist():
        messages.error(request, "Доступ запрещён")
        return redirect('accounts:dashboard')

    from accounts.models import User
    from scheduling.models import LessonFeedback

    teacher = get_object_or_404(User, pk=teacher_id, role=User.UserRole.TEACHER)
    feedbacks = (
        LessonFeedback.objects
        .filter(is_teacher=False, lesson__teacher_id=teacher_id)
        .select_related('lesson', 'user')
        .order_by('-created_at')
    )

    context = {
        'teacher': teacher,
        'feedbacks': feedbacks,
    }
    return render(request, 'assignments/teacher_feedback_list.html', context)
