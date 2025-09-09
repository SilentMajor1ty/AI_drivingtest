#!/usr/bin/env python
"""
Script to create initial data for the driving school application
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'driving_school.settings')
sys.path.append('/home/runner/work/AI_drivingtest/AI_drivingtest')
django.setup()

from accounts.models import User, UserProfile
from scheduling.models import Subject, LessonTemplate
from django.db import transaction

def create_initial_data():
    """Create initial data for the application"""
    
    with transaction.atomic():
        # Create Methodist (admin) user
        if not User.objects.filter(username='methodist').exists():
            methodist = User.objects.create_user(
                username='methodist',
                email='methodist@drivingschool.com',
                password='methodist123',
                first_name='John',
                last_name='Methodist',
                role=User.UserRole.METHODIST
            )
            methodist.is_staff = True
            methodist.is_superuser = True
            methodist.save()
            
            UserProfile.objects.create(user=methodist)
            print(f"Created Methodist user: {methodist.username}")
        
        # Create a sample teacher
        if not User.objects.filter(username='teacher1').exists():
            teacher = User.objects.create_user(
                username='teacher1',
                email='teacher1@drivingschool.com', 
                password='teacher123',
                first_name='Sarah',
                last_name='Smith',
                role=User.UserRole.TEACHER,
                created_by=User.objects.get(username='methodist')
            )
            
            UserProfile.objects.create(
                user=teacher,
                specialization='Driving Theory and Practice',
                experience_years=5
            )
            print(f"Created Teacher user: {teacher.username}")
        
        # Create a sample student
        if not User.objects.filter(username='student1').exists():
            student = User.objects.create_user(
                username='student1',
                email='student1@drivingschool.com',
                password='student123',
                first_name='Mike',
                last_name='Johnson',
                role=User.UserRole.STUDENT,
                created_by=User.objects.get(username='methodist')
            )
            
            from datetime import date
            UserProfile.objects.create(
                user=student,
                enrollment_date=date.today()
            )
            print(f"Created Student user: {student.username}")
        
        # Create subjects
        subjects_data = [
            ('Driving Theory', 'Traffic laws, road signs, and driving theory'),
            ('Practical Driving', 'Hands-on driving lessons'),
            ('Road Safety', 'Safety protocols and emergency procedures'),
        ]
        
        for name, description in subjects_data:
            if not Subject.objects.filter(name=name).exists():
                Subject.objects.create(name=name, description=description)
                print(f"Created Subject: {name}")
        
        # Create lesson templates
        methodist = User.objects.get(username='methodist')
        theory_subject = Subject.objects.get(name='Driving Theory')
        
        if not LessonTemplate.objects.filter(name='Basic Theory Lesson').exists():
            LessonTemplate.objects.create(
                name='Basic Theory Lesson',
                subject=theory_subject,
                title_template='Theory Lesson {lesson_number}',
                description_template='Basic driving theory covering traffic rules and regulations',
                default_duration_minutes=60,
                created_by=methodist
            )
            print("Created lesson template: Basic Theory Lesson")
        
        print("Initial data creation completed!")

if __name__ == '__main__':
    create_initial_data()