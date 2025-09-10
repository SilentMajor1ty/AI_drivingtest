#!/usr/bin/env python
import os
import django
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'driving_school.settings')
django.setup()

from accounts.models import User
from scheduling.models import Subject, Lesson
from django.utils import timezone

# Create subjects
driving_theory, created = Subject.objects.get_or_create(
    name='Driving Theory',
    defaults={'description': 'Theoretical knowledge about driving rules and road safety'}
)

practical_driving, created = Subject.objects.get_or_create(
    name='Practical Driving',
    defaults={'description': 'Hands-on driving practice with instructor'}
)

# Create users
methodist, created = User.objects.get_or_create(
    username='methodist',
    defaults={
        'email': 'methodist@test.com',
        'first_name': 'Методист',
        'last_name': 'Иванов',
        'role': User.UserRole.METHODIST
    }
)
if created:
    methodist.set_password('methodist123')
    methodist.save()

teacher1, created = User.objects.get_or_create(
    username='teacher1', 
    defaults={
        'email': 'teacher1@test.com',
        'first_name': 'Анна',
        'last_name': 'Смирнова',
        'role': User.UserRole.TEACHER
    }
)
if created:
    teacher1.set_password('teacher123')
    teacher1.save()

teacher2, created = User.objects.get_or_create(
    username='teacher2',
    defaults={
        'email': 'teacher2@test.com', 
        'first_name': 'Петр',
        'last_name': 'Козлов',
        'role': User.UserRole.TEACHER
    }
)
if created:
    teacher2.set_password('teacher123')
    teacher2.save()

student1, created = User.objects.get_or_create(
    username='student1',
    defaults={
        'email': 'student1@test.com',
        'first_name': 'Михаил',
        'last_name': 'Васильев',
        'role': User.UserRole.STUDENT
    }
)
if created:
    student1.set_password('student123')
    student1.save()

student2, created = User.objects.get_or_create(
    username='student2',
    defaults={
        'email': 'student2@test.com',
        'first_name': 'Елена',
        'last_name': 'Попова', 
        'role': User.UserRole.STUDENT
    }
)
if created:
    student2.set_password('student123')
    student2.save()

# Create some lessons
tomorrow = timezone.now() + timedelta(days=1)
lesson_time1 = tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)

# Create the lesson that we saw in the calendar
if not Lesson.objects.filter(title='Тестовое занятие по вождению').exists():
    Lesson.objects.create(
        title='Тестовое занятие по вождению',
        subject=driving_theory,
        teacher=teacher1,
        student=student1,
        start_time=lesson_time1,
        end_time=lesson_time1 + timedelta(hours=1),
        description='Первое занятие по теории вождения',
        zoom_link='https://zoom.us/j/123456789',
        created_by=methodist
    )

# Add more lessons for variety
lesson_time2 = lesson_time1 + timedelta(days=2, hours=2)
if not Lesson.objects.filter(title='Практическое вождение').exists():
    Lesson.objects.create(
        title='Практическое вождение',
        subject=practical_driving,
        teacher=teacher2,
        student=student2,
        start_time=lesson_time2,
        end_time=lesson_time2 + timedelta(hours=1, minutes=30),
        description='Практическое занятие по вождению',
        zoom_link='https://zoom.us/j/987654321',
        created_by=methodist
    )

lesson_time3 = lesson_time1 + timedelta(days=7)
if not Lesson.objects.filter(title='Повторение правил дорожного движения').exists():
    Lesson.objects.create(
        title='Повторение правил дорожного движения',
        subject=driving_theory,
        teacher=teacher1,
        student=student2,
        start_time=lesson_time3,
        end_time=lesson_time3 + timedelta(hours=1),
        description='Повторное изучение ПДД',
        zoom_link='https://meet.google.com/xyz-abc-def',
        created_by=methodist
    )

print("Demo data created successfully!")
print("Available users:")
print("- Methodist: methodist / methodist123")
print("- Teacher 1: teacher1 / teacher123")
print("- Teacher 2: teacher2 / teacher123")  
print("- Student 1: student1 / student123")
print("- Student 2: student2 / student123")