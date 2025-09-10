#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'driving_school.settings')
django.setup()

from accounts.models import User

# Create superuser
if not User.objects.filter(username='admin').exists():
    user = User.objects.create_user(
        username='admin',
        email='admin@test.com',
        password='admin123',
        first_name='Admin',
        last_name='User',
        role=User.UserRole.METHODIST
    )
    user.is_superuser = True
    user.is_staff = True
    user.save()
    print("Superuser 'admin' created successfully!")
else:
    print("Superuser 'admin' already exists!")