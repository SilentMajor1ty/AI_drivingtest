from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, DetailView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db import models

from .models import Assignment, AssignmentSubmission, Notification
from .forms import AssignmentForm, AssignmentSubmissionForm


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
        elif status_filter == 'graded':
            queryset = queryset.filter(status=Assignment.AssignmentStatus.REVIEWED)
        # 'all' shows everything (no additional filtering)
        
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
            'all': base_queryset.count(),
            'overdue': base_queryset.filter(
                due_date__lt=timezone.now(),
                status__in=[Assignment.AssignmentStatus.ASSIGNED, Assignment.AssignmentStatus.IN_PROGRESS, Assignment.AssignmentStatus.NEEDS_REVISION]
            ).count(),
            'graded': base_queryset.filter(status=Assignment.AssignmentStatus.REVIEWED).count(),
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
        context['submissions'] = self.object.submissions.all().order_by('-submitted_at')
        
        # Get assignment materials from non-final submissions (uploaded during assignment creation)
        assignment_materials = self.object.submissions.filter(is_final=False).first()
        context['assignment_materials'] = assignment_materials
        
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
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
        # Handle multiple file uploads
        assignment_files = self.request.FILES.getlist('assignment_files')
        if assignment_files:
            from .models import AssignmentSubmission, AssignmentFile
            
            # Create a default submission for the assignment materials
            submission = AssignmentSubmission.objects.create(
                assignment=self.object,
                comments="Assignment materials",
                is_final=False  # This is not a student submission
            )
            
            # Add all uploaded files
            for file in assignment_files:
                AssignmentFile.objects.create(
                    submission=submission,
                    file=file,
                    original_name=file.name
                )
        
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
        
        # Create submission
        submission = AssignmentSubmission.objects.create(
            assignment=assignment,
            comments=comments
        )
        
        # Handle multiple files
        if submission_files:
            from .models import AssignmentFile
            for file in submission_files:
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
    """API endpoint to get user notifications"""
    notifications = Notification.objects.filter(user=request.user).order_by('-sent_at')
    
    # Get unread count first, before slicing
    unread_count = notifications.filter(is_read=False).count()
    
    # Then slice for display
    notifications_limited = notifications[:10]
    
    data = {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'sent_at': n.sent_at.strftime('%d.%m.%Y %H:%M'),
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
def upload_assignment_files(request, submission_id):
    """Upload additional files to assignment submission"""
    from .models import AssignmentFile
    
    submission = get_object_or_404(AssignmentSubmission, pk=submission_id)
    
    if request.user != submission.assignment.student:
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    if request.method == 'POST':
        uploaded_files = request.FILES.getlist('files')
        
        # Validate file sizes (200MB limit per file)
        max_size = 200 * 1024 * 1024  # 200MB in bytes
        for file in uploaded_files:
            if file.size > max_size:
                return JsonResponse({
                    'success': False, 
                    'error': f'File "{file.name}" is too large. Maximum size is 200MB.'
                })
        
        # Create file records
        created_files = []
        for file in uploaded_files:
            assignment_file = AssignmentFile.objects.create(
                submission=submission,
                file=file,
                original_name=file.name
            )
            created_files.append(assignment_file)
        
        return JsonResponse({
            'success': True, 
            'message': f'{len(uploaded_files)} files uploaded successfully'
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def delete_assignment_file(request, file_id):
    """Delete assignment file"""
    from .models import AssignmentFile
    
    file = get_object_or_404(AssignmentFile, pk=file_id)
    
    if request.user != file.submission.assignment.student:
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    if request.method == 'POST':
        file.delete()
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
def methodist_analytics(request):
    """Analytics dashboard for methodist"""
    if not request.user.is_methodist():
        messages.error(request, "Access denied. Only methodists can view analytics.")
        return redirect('accounts:dashboard')
    
    from django.db.models import Avg, Count
    from scheduling.models import Lesson
    from accounts.models import User
    
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
    
    # Average lesson ratings
    lesson_ratings = Lesson.objects.filter(
        status=Lesson.LessonStatus.COMPLETED,
        teacher_rating__isnull=False,
        student_rating__isnull=False
    ).aggregate(
        avg_teacher_rating=Avg('teacher_rating'),
        avg_student_rating=Avg('student_rating')
    )
    
    # Attendance rate (lessons that were confirmed vs scheduled)
    scheduled_lessons = Lesson.objects.filter(
        status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.COMPLETED]
    ).count()
    attendance_rate = (completed_lessons / scheduled_lessons * 100) if scheduled_lessons > 0 else 0
    
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
    }
    
    return render(request, 'assignments/methodist_analytics.html', context)
