from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import FileExtensionValidator

User = get_user_model()


class Assignment(models.Model):
    """
    Homework assignments for students
    """
    
    class AssignmentStatus(models.TextChoices):
        ASSIGNED = 'assigned', 'Assigned'
        IN_PROGRESS = 'in_progress', 'In Progress'  
        SUBMITTED = 'submitted', 'Submitted'
        REVIEWED = 'reviewed', 'Reviewed'
        COMPLETED = 'completed', 'Completed'
        NEEDS_REVISION = 'needs_revision', 'Needs Revision'
    
    # Basic assignment information
    title = models.CharField(max_length=200)
    description = models.TextField()
    
    # Relationships
    lesson = models.ForeignKey(
        'scheduling.Lesson',
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='assignments',
        limit_choices_to={'role': User.UserRole.STUDENT}
    )
    
    # Files and materials
    assignment_file = models.FileField(
        upload_to='assignments/materials/',
        blank=True,
        null=True,
        help_text="Assignment materials from teacher"
    )
    
    # Deadlines and status
    due_date = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Teacher feedback
    teacher_comments = models.TextField(blank=True)
    grade = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Grade from 1-10"
    )
    
    # Created by
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_assignments'
    )
    
    @property
    def is_overdue(self):
        """Check if assignment is past due date"""
        return timezone.now() > self.due_date and self.status != self.AssignmentStatus.COMPLETED
    
    @property
    def days_until_due(self):
        """Calculate days until due date"""
        if self.due_date:
            delta = self.due_date - timezone.now()
            return delta.days
        return None
    
    def mark_submitted(self):
        """Mark assignment as submitted"""
        self.status = self.AssignmentStatus.SUBMITTED
        self.submitted_at = timezone.now()
        self.save()
    
    def mark_reviewed(self, teacher_comments="", grade=None):
        """Mark assignment as reviewed by teacher"""
        self.status = self.AssignmentStatus.REVIEWED
        self.reviewed_at = timezone.now()
        if teacher_comments:
            self.teacher_comments = teacher_comments
        if grade is not None:
            self.grade = grade
        self.save()
    
    def __str__(self):
        return f"{self.title} - {self.student.full_name}"
    
    class Meta:
        ordering = ['-due_date']
        verbose_name = 'Assignment'
        verbose_name_plural = 'Assignments'


class AssignmentSubmission(models.Model):
    """
    Student submissions for assignments with version control
    """
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name='submissions'
    )
    
    # File submission
    submission_file = models.FileField(
        upload_to='assignments/submissions/',
        validators=[
            FileExtensionValidator(
                allowed_extensions=['pdf', 'doc', 'docx', 'txt', 'jpg', 'png', 'zip']
            )
        ]
    )
    
    # Metadata
    version = models.PositiveIntegerField(default=1)
    comments = models.TextField(blank=True, help_text="Student's comments about this submission")
    
    # Timestamps
    submitted_at = models.DateTimeField(auto_now_add=True)
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    
    # Status
    is_final = models.BooleanField(default=True, help_text="Is this the final submission?")
    
    class Meta:
        ordering = ['-submitted_at']
        verbose_name = 'Assignment Submission'
        verbose_name_plural = 'Assignment Submissions'
    
    def save(self, *args, **kwargs):
        # Set file size automatically
        if self.submission_file:
            self.file_size = self.submission_file.size
            
        # Auto-increment version number
        if not self.pk:
            last_submission = AssignmentSubmission.objects.filter(
                assignment=self.assignment
            ).order_by('-version').first()
            
            if last_submission:
                self.version = last_submission.version + 1
                # Mark previous submissions as not final
                AssignmentSubmission.objects.filter(
                    assignment=self.assignment,
                    is_final=True
                ).update(is_final=False)
        
        super().save(*args, **kwargs)
        
        # Update assignment status
        if self.is_final:
            self.assignment.mark_submitted()
    
    def __str__(self):
        return f"{self.assignment.title} - v{self.version}"


class AssignmentTemplate(models.Model):
    """
    Template for common assignments to help Methodist create assignments faster
    """
    name = models.CharField(max_length=200)
    title_template = models.CharField(max_length=200)
    description_template = models.TextField()
    
    # Default settings
    default_duration_days = models.PositiveIntegerField(
        default=7,
        help_text="Default number of days to complete assignment"
    )
    
    # Template files
    template_file = models.FileField(
        upload_to='assignment_templates/',
        blank=True,
        null=True
    )
    
    # Subject relation
    subject = models.ForeignKey(
        'scheduling.Subject',
        on_delete=models.CASCADE,
        related_name='assignment_templates'
    )
    
    # Created by Methodist
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'role': User.UserRole.METHODIST}
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.subject.name})"
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Assignment Template'
        verbose_name_plural = 'Assignment Templates'


class Notification(models.Model):
    """
    System notifications for users
    """
    
    class NotificationType(models.TextChoices):
        LESSON_CREATED = 'lesson_created', 'Lesson Created'
        LESSON_UPDATED = 'lesson_updated', 'Lesson Updated'
        LESSON_REMINDER_24H = 'lesson_reminder_24h', '24h Lesson Reminder'
        LESSON_REMINDER_1H = 'lesson_reminder_1h', '1h Lesson Reminder'
        ASSIGNMENT_ASSIGNED = 'assignment_assigned', 'Assignment Assigned'
        ASSIGNMENT_DUE_SOON = 'assignment_due_soon', 'Assignment Due Soon'
        ASSIGNMENT_OVERDUE = 'assignment_overdue', 'Assignment Overdue'
        ASSIGNMENT_SUBMITTED = 'assignment_submitted', 'Assignment Submitted'
        ASSIGNMENT_REVIEWED = 'assignment_reviewed', 'Assignment Reviewed'
    
    # Recipients
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    
    # Notification content
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Related objects (optional)
    lesson = models.ForeignKey(
        'scheduling.Lesson',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE, 
        null=True,
        blank=True,
        related_name='notifications'
    )
    
    # Status
    is_read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Delivery channels
    sent_push = models.BooleanField(default=False)
    sent_email = models.BooleanField(default=False)
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()
    
    def __str__(self):
        return f"{self.title} - {self.user.full_name}"
    
    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
