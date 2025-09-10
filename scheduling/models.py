from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from datetime import timedelta
import pytz

User = get_user_model()


class Subject(models.Model):
    """
    Subject/Course definition
    """
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['name']


class Lesson(models.Model):
    """
    Individual lesson/class session
    """
    
    class LessonStatus(models.TextChoices):
        SCHEDULED = 'scheduled', 'Scheduled'
        COMPLETED = 'completed', 'Completed' 
        CANCELLED = 'cancelled', 'Cancelled'
        RESCHEDULED = 'rescheduled', 'Rescheduled'
    
    # Basic lesson information
    title = models.CharField(max_length=200)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='lessons')
    teacher = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='teaching_lessons',
        limit_choices_to={'role': User.UserRole.TEACHER}
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='student_lessons', 
        limit_choices_to={'role': User.UserRole.STUDENT}
    )
    
    # Scheduling
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    # Content and materials
    description = models.TextField(blank=True)
    materials = models.FileField(upload_to='lesson_materials/', blank=True, null=True)
    teacher_materials = models.FileField(
        upload_to='lesson_teacher_materials/',
        blank=True,
        null=True,
        help_text="Материалы для преподавателя (видны только преподавателю)"
    )
    zoom_link = models.URLField(blank=True, help_text="Zoom/Meet meeting link")
    
    # Status and tracking
    status = models.CharField(
        max_length=20,
        choices=LessonStatus.choices,
        default=LessonStatus.SCHEDULED
    )
    
    # Ratings (1-10 scale)
    teacher_rating = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Teacher's rating of the lesson (1-10)"
    )
    student_rating = models.PositiveIntegerField(
        null=True, blank=True, 
        help_text="Student's rating of the lesson (1-10)"
    )
    
    # Comments
    teacher_comments = models.TextField(blank=True)
    student_comments = models.TextField(blank=True)
    
    # Lesson completion tracking
    teacher_confirmed_completion = models.BooleanField(default=False, help_text="Преподаватель подтвердил проведение урока")
    student_confirmed_completion = models.BooleanField(default=False, help_text="Ученик подтвердил посещение урока")
    completion_confirmed_at = models.DateTimeField(null=True, blank=True, help_text="Когда урок был подтвержден обеими сторонами")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_lessons',
        limit_choices_to={'role': User.UserRole.METHODIST}
    )
    
    def clean(self):
        """Validate lesson data"""
        super().clean()
        
        # Check duration (minimum 30 minutes)
        if self.start_time and self.end_time:
            duration = self.end_time - self.start_time
            if duration < timedelta(minutes=30):
                raise ValidationError("Minimum lesson duration is 30 minutes")
            
            # Check for overlapping lessons for teacher
            overlapping_teacher = Lesson.objects.filter(
                teacher=self.teacher,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
                status__in=[self.LessonStatus.SCHEDULED, self.LessonStatus.COMPLETED]
            ).exclude(pk=self.pk)
            
            if overlapping_teacher.exists():
                raise ValidationError("Teacher has conflicting lesson at this time")
            
            # Check for overlapping lessons for student  
            overlapping_student = Lesson.objects.filter(
                student=self.student,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
                status__in=[self.LessonStatus.SCHEDULED, self.LessonStatus.COMPLETED]
            ).exclude(pk=self.pk)
            
            if overlapping_student.exists():
                raise ValidationError("Student has conflicting lesson at this time")
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    
    @property
    def duration_minutes(self):
        """Return lesson duration in minutes"""
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds() / 60)
        return 0
    
    @property
    def can_be_confirmed(self):
        """Check if lesson can be confirmed (lesson time has passed)"""
        return (
            self.status == self.LessonStatus.SCHEDULED and 
            timezone.now() > self.end_time
        )
    
    @property
    def is_confirmed_by_both(self):
        """Check if lesson is confirmed by both teacher and student"""
        return self.teacher_confirmed_completion and self.student_confirmed_completion
    
    def confirm_completion_by_teacher(self, rating=None, comments=""):
        """Confirm lesson completion by teacher"""
        self.teacher_confirmed_completion = True
        if rating:
            self.teacher_rating = rating
        if comments:
            self.teacher_comments = comments
        
        if self.is_confirmed_by_both:
            self.status = self.LessonStatus.COMPLETED
            self.completion_confirmed_at = timezone.now()
        
        self.save()
    
    def confirm_completion_by_student(self, rating=None, comments=""):
        """Confirm lesson completion by student"""
        self.student_confirmed_completion = True
        if rating:
            self.student_rating = rating
        if comments:
            self.student_comments = comments
        
        if self.is_confirmed_by_both:
            self.status = self.LessonStatus.COMPLETED
            self.completion_confirmed_at = timezone.now()
        
        self.save()
    
    @property
    def can_be_rated(self):
        """Check if lesson can be rated (completed and time has passed)"""
        return (
            self.status == self.LessonStatus.COMPLETED and 
            timezone.now() > self.end_time
        )
    
    def get_local_start_time(self, user_timezone):
        """Get start time in user's timezone"""
        user_tz = pytz.timezone(str(user_timezone))
        return self.start_time.astimezone(user_tz)
    
    def get_local_end_time(self, user_timezone):
        """Get end time in user's timezone"""
        user_tz = pytz.timezone(str(user_timezone))
        return self.end_time.astimezone(user_tz)
    
    def __str__(self):
        return f"{self.title} - {self.teacher.full_name} & {self.student.full_name}"
    
    class Meta:
        ordering = ['-start_time']
        verbose_name = 'Lesson'
        verbose_name_plural = 'Lessons'


class ProblemReport(models.Model):
    """
    Problem reports from students during lessons
    """
    
    class ProblemType(models.TextChoices):
        CONNECTION = 'connection', 'Проблемы с подключением'
        AUDIO = 'audio', 'Проблемы со звуком'
        VIDEO = 'video', 'Проблемы с видео'
        TECHNICAL = 'technical', 'Технические проблемы'
        OTHER = 'other', 'Другое'
    
    lesson = models.ForeignKey(
        Lesson, 
        on_delete=models.CASCADE, 
        related_name='problem_reports'
    )
    reporter = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='reported_problems'
    )
    problem_type = models.CharField(
        max_length=20,
        choices=ProblemType.choices,
        default=ProblemType.OTHER
    )
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_problems'
    )
    
    def __str__(self):
        return f"Проблема в занятии {self.lesson.title} от {self.reporter.full_name}"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Отчет о проблеме'
        verbose_name_plural = 'Отчеты о проблемах'


class LessonTemplate(models.Model):
    """
    Template for recurring lessons to simplify Methodist's work
    """
    name = models.CharField(max_length=200)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    title_template = models.CharField(max_length=200, help_text="Template for lesson titles")
    description_template = models.TextField(blank=True)
    default_duration_minutes = models.PositiveIntegerField(default=60)
    materials = models.FileField(upload_to='lesson_templates/', blank=True, null=True)
    
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


class Schedule(models.Model):
    """
    Weekly schedule template for teachers
    """
    
    class WeekDay(models.IntegerChoices):
        MONDAY = 1, 'Monday'
        TUESDAY = 2, 'Tuesday'
        WEDNESDAY = 3, 'Wednesday'
        THURSDAY = 4, 'Thursday'
        FRIDAY = 5, 'Friday'
        SATURDAY = 6, 'Saturday'
        SUNDAY = 7, 'Sunday'
    
    teacher = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='schedule_slots',
        limit_choices_to={'role': User.UserRole.TEACHER}
    )
    
    day_of_week = models.IntegerField(choices=WeekDay.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    is_available = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.teacher.full_name} - {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"
    
    class Meta:
        ordering = ['teacher', 'day_of_week', 'start_time']
        unique_together = ['teacher', 'day_of_week', 'start_time', 'end_time']


class LessonFile(models.Model):
    """
    Multiple files for lesson materials
    """
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='lesson_files'
    )
    
    file = models.FileField(
        upload_to='lesson_files/',
        validators=[
            FileExtensionValidator(
                allowed_extensions=['pdf', 'doc', 'docx', 'txt', 'jpg', 'png', 'zip']
            )
        ]
    )
    
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    is_teacher_material = models.BooleanField(default=False, help_text="Видимо только преподавателю")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size
            if not self.original_name:
                self.original_name = self.file.name
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.lesson.title} - {self.original_name}"
    
    class Meta:
        ordering = ['-uploaded_at']
