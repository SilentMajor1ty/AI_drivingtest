from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, DetailView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse

from .models import Assignment, AssignmentSubmission, Notification


class AssignmentListView(LoginRequiredMixin, ListView):
    """List assignments based on user role"""
    model = Assignment
    template_name = 'assignments/assignment_list.html'
    context_object_name = 'assignments'
    paginate_by = 10
    
    def get_queryset(self):
        user = self.request.user
        
        if user.is_student():
            return Assignment.objects.filter(student=user).select_related('lesson', 'lesson__subject')
        elif user.is_teacher():
            return Assignment.objects.filter(lesson__teacher=user).select_related('student', 'lesson', 'lesson__subject')
        else:  # Methodist
            return Assignment.objects.all().select_related('student', 'lesson', 'lesson__subject')


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
            return Assignment.objects.filter(lesson__teacher=user)
        else:  # Methodist
            return Assignment.objects.all()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['submissions'] = self.object.submissions.all().order_by('-submitted_at')
        return context


class AssignmentCreateView(LoginRequiredMixin, CreateView):
    """Create new assignment - Methodist and Teachers"""
    model = Assignment
    template_name = 'assignments/assignment_form.html'
    fields = ['title', 'description', 'lesson', 'student', 'due_date', 'assignment_file']
    success_url = reverse_lazy('assignments:assignment_list')
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_student():
            messages.error(request, "Students cannot create assignments.")
            return redirect('assignments:assignment_list')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        
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
    
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        
        user = self.request.user
        if user.is_teacher():
            # Teachers can only assign to their students
            form.fields['lesson'].queryset = form.fields['lesson'].queryset.filter(teacher=user)
            form.fields['student'].queryset = form.fields['student'].queryset.filter(
                student_lessons__teacher=user
            ).distinct()
        
        return form


@login_required
def submit_assignment(request, pk):
    """Submit assignment - Students only"""
    assignment = get_object_or_404(Assignment, pk=pk)
    
    if request.user != assignment.student:
        messages.error(request, "You can only submit your own assignments.")
        return redirect('assignments:assignment_detail', pk=pk)
    
    if request.method == 'POST':
        submission_file = request.FILES.get('submission_file')
        comments = request.POST.get('comments', '')
        
        if not submission_file:
            messages.error(request, "Please select a file to submit.")
            return redirect('assignments:assignment_detail', pk=pk)
        
        # Create submission
        submission = AssignmentSubmission.objects.create(
            assignment=assignment,
            submission_file=submission_file,
            comments=comments
        )
        
        # Create notification for teacher
        Notification.objects.create(
            user=assignment.lesson.teacher,
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
