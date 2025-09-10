from django import forms
from django.utils import timezone
from .models import Lesson, Subject
from accounts.models import User
from datetime import datetime, timedelta


class LessonForm(forms.ModelForm):
    """Form for creating and updating lessons with improved time input"""
    
    # Separate date and time fields for better UX
    lesson_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        help_text="Выберите дату занятия"
    )
    
    # Changed to time input instead of dropdowns
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        help_text="Введите время начала (например: 14:30)"
    )
    
    duration_minutes = forms.ChoiceField(
        choices=[
            (30, "30 минут"),
            (45, "45 минут"),
            (60, "1 час"),
            (90, "1.5 часа"),
            (120, "2 часа"),
        ],
        initial=60,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Продолжительность занятия"
    )
    
    class Meta:
        model = Lesson
        # Removed description field
        fields = ['title', 'subject', 'teacher', 'student', 'teacher_materials', 'zoom_link']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название занятия'}),
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'teacher': forms.Select(attrs={'class': 'form-select'}),
            'student': forms.Select(attrs={'class': 'form-select'}),
            'teacher_materials': forms.FileInput(attrs={'class': 'form-control'}),
            'zoom_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://zoom.us/j/...'})
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter teacher and student choices
        self.fields['teacher'].queryset = User.objects.filter(role=User.UserRole.TEACHER)
        self.fields['student'].queryset = User.objects.filter(role=User.UserRole.STUDENT)
        
        # Initialize form with existing lesson data if editing
        if self.instance and self.instance.pk:
            self.fields['lesson_date'].initial = self.instance.start_time.date()
            self.fields['start_time'].initial = self.instance.start_time.time()
            duration = int((self.instance.end_time - self.instance.start_time).total_seconds() / 60)
            self.fields['duration_minutes'].initial = duration
    
    def clean(self):
        cleaned_data = super().clean()
        lesson_date = cleaned_data.get('lesson_date')
        start_time = cleaned_data.get('start_time')
        duration_minutes = cleaned_data.get('duration_minutes')
        teacher = cleaned_data.get('teacher')
        student = cleaned_data.get('student')
        
        if all([lesson_date, start_time, duration_minutes]):
            # Construct start_datetime and end_datetime
            start_datetime = timezone.make_aware(datetime.combine(lesson_date, start_time))
            end_datetime = start_datetime + timedelta(minutes=int(duration_minutes))
            
            # Check if the lesson is in the past with 5-minute buffer
            current_time = timezone.now()
            min_allowed_time = current_time + timedelta(minutes=5)
            if start_datetime < min_allowed_time:
                raise forms.ValidationError(
                    f"Нельзя назначить занятие на прошедшее время. "
                    f"Минимальное время для назначения: {min_allowed_time.strftime('%H:%M')}"
                )
            
            # Check for 15-minute break between lessons for teacher
            if teacher:
                # Check lessons ending before this one
                previous_lessons = Lesson.objects.filter(
                    teacher=teacher,
                    end_time__lte=start_datetime,
                    status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.COMPLETED]
                ).exclude(pk=self.instance.pk if self.instance else None).order_by('-end_time')
                
                if previous_lessons.exists():
                    last_lesson_end = previous_lessons.first().end_time
                    if start_datetime - last_lesson_end < timedelta(minutes=15):
                        raise forms.ValidationError(
                            f"Требуется 15-минутный перерыв между занятиями преподавателя. "
                            f"Предыдущее занятие заканчивается в {last_lesson_end.strftime('%H:%M')}"
                        )
                
                # Check lessons starting after this one
                next_lessons = Lesson.objects.filter(
                    teacher=teacher,
                    start_time__gte=end_datetime,
                    status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.COMPLETED]
                ).exclude(pk=self.instance.pk if self.instance else None).order_by('start_time')
                
                if next_lessons.exists():
                    next_lesson_start = next_lessons.first().start_time
                    if next_lesson_start - end_datetime < timedelta(minutes=15):
                        raise forms.ValidationError(
                            f"Требуется 15-минутный перерыв между занятиями преподавателя. "
                            f"Следующее занятие начинается в {next_lesson_start.strftime('%H:%M')}"
                        )
            
            cleaned_data['start_datetime'] = start_datetime
            cleaned_data['end_datetime'] = end_datetime
        
        return cleaned_data
    
    def save(self, commit=True):
        lesson = super().save(commit=False)
        lesson.start_time = self.cleaned_data['start_datetime']
        lesson.end_time = self.cleaned_data['end_datetime']
        if commit:
            lesson.save()
        return lesson