from django.contrib.auth.models import AbstractUser
from django.db import models
from timezone_field import TimeZoneField
import pytz


class User(AbstractUser):
    """
    Custom user model with role-based access control.
    Supports three roles: Student, Teacher, Methodist
    """
    
    class UserRole(models.TextChoices):
        STUDENT = 'student', 'Ученик'
        TEACHER = 'teacher', 'Инструктор'  
        METHODIST = 'methodist', 'Методист'
    
    # Basic profile information
    first_name = models.CharField(max_length=150, verbose_name='Имя')
    last_name = models.CharField(max_length=150, verbose_name='Фамилия')
    middle_name = models.CharField(max_length=150, blank=True, verbose_name='Отчество')
    
    # Role-based access
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.STUDENT,
        verbose_name='Роль'
    )
    
    # Time zone - automatically detected, no longer exposed in forms
    timezone = TimeZoneField(default='Europe/Moscow', verbose_name='Часовой пояс')
    
    # Profile information
    phone = models.CharField(max_length=20, blank=True, verbose_name='Телефон')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    # Only methodist can create accounts
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        limit_choices_to={'role': UserRole.METHODIST},
        verbose_name='Создан пользователем'
    )
    
    def save(self, *args, **kwargs):
        # Set default timezone if not set
        if not self.timezone:
            self.timezone = 'Europe/Moscow'
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_role_display()})"
    
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
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'


class UserProfile(models.Model):
    """
    Extended profile information for users
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name='Пользователь')
    
    # Additional profile fields
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, verbose_name='Аватар')
    bio = models.TextField(max_length=500, blank=True, verbose_name='О себе')
    
    # Notification preferences
    email_notifications = models.BooleanField(default=True, verbose_name='Email уведомления')
    push_notifications = models.BooleanField(default=True, verbose_name='Push уведомления')
    
    # Student specific fields
    enrollment_date = models.DateField(null=True, blank=True, verbose_name='Дата зачисления')
    
    # Teacher specific fields  
    specialization = models.CharField(max_length=200, blank=True, verbose_name='Специализация')
    experience_years = models.PositiveIntegerField(default=0, verbose_name='Лет опыта')
    
    def __str__(self):
        return f"Профиль {self.user.full_name}"
    
    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'
