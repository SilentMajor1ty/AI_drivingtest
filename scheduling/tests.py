from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from .models import Lesson, LessonFeedback, Subject


class FeedbackAPITest(TestCase):
    def setUp(self):
        # Create users
        self.teacher = User.objects.create_user(username='teacher1', password='pass', first_name='T', last_name='One')
        self.teacher.role = User.UserRole.TEACHER
        self.teacher.save()

        self.student = User.objects.create_user(username='student1', password='pass', first_name='S', last_name='One')
        self.student.role = User.UserRole.STUDENT
        self.student.save()

        # Subject
        self.subject = Subject.objects.create(name='Math')

        # Create a completed lesson in the past
        now = timezone.now()
        self.lesson = Lesson.objects.create(
            title='Test Lesson',
            subject=self.subject,
            teacher=self.teacher,
            student=self.student,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1, minutes=30),
            status=Lesson.LessonStatus.COMPLETED,
        )

        self.client = Client()

    def test_feedback_pending_and_submit(self):
        # Student must login
        logged = self.client.login(username='student1', password='pass')
        self.assertTrue(logged)

        # pending should show this lesson
        resp = self.client.get(reverse('scheduling:feedback_pending'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('pending'))
        self.assertIn('lesson', data)
        self.assertEqual(data['lesson']['id'], self.lesson.id)

        # submit feedback
        submit_url = reverse('scheduling:feedback_submit')
        resp2 = self.client.post(submit_url, data={"lesson_id": self.lesson.id, "rating": 8}, content_type='application/json')
        self.assertEqual(resp2.status_code, 200)
        j = resp2.json()
        self.assertEqual(j.get('status'), 'ok')

        # second submit should be rejected (409)
        resp3 = self.client.post(submit_url, data={"lesson_id": self.lesson.id, "rating": 7}, content_type='application/json')
        self.assertIn(resp3.status_code, (400, 403, 409))

        # Verify DB entry
        fb = LessonFeedback.objects.filter(lesson=self.lesson, user=self.student).first()
        self.assertIsNotNone(fb)
        self.assertEqual(fb.rating, 8)

    def test_nonstudent_cannot_submit(self):
        # Teacher tries to submit -> forbidden
        logged = self.client.login(username='teacher1', password='pass')
        self.assertTrue(logged)
        submit_url = reverse('scheduling:feedback_submit')
        resp = self.client.post(submit_url, data={"lesson_id": self.lesson.id, "rating": 9}, content_type='application/json')
        self.assertIn(resp.status_code, (403, 400))
