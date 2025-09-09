from django.contrib.auth.models import AbstractUser
from django.db import models
from timezone_field import TimeZoneField


class User(AbstractUser):
    """
    Custom user model with role-based access control.
    Supports three roles: Student, Teacher, Methodist
    """
    
    class UserRole(models.TextChoices):
        STUDENT = 'student', 'Student'
        TEACHER = 'teacher', 'Teacher'  
        METHODIST = 'methodist', 'Methodist'
    
    # Basic profile information
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    middle_name = models.CharField(max_length=150, blank=True)
    
    # Role-based access
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.STUDENT
    )
    
    # Time zone for proper scheduling - simplified default
    timezone = TimeZoneField(default='UTC')
    
    # Profile information
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Only methodist can create accounts
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        limit_choices_to={'role': UserRole.METHODIST}
    )
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.role})"
    
    @property
    def full_name(self):
        """Return full name including middle name if available"""
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name}"
        return f"{self.first_name} {self.last_name}"
    
    def is_student(self):
        return self.role == self.UserRole.STUDENT
    
    def is_teacher(self):
        return self.role == self.UserRole.TEACHER
    
    def is_methodist(self):
        return self.role == self.UserRole.METHODIST
    
    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = 'User'
        verbose_name_plural = 'Users'


class UserProfile(models.Model):
    """
    Extended profile information for users
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Additional profile fields
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    
    # Student specific fields
    enrollment_date = models.DateField(null=True, blank=True)
    
    # Teacher specific fields  
    specialization = models.CharField(max_length=200, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"Profile of {self.user.full_name}"
    
    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
