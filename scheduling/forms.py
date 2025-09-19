from django import forms
from django.utils import timezone
from .models import Lesson
from accounts.models import User
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class LessonForm(forms.ModelForm):
    """Form for creating and updating lessons with improved time input"""
    
    # Separate date and time fields for better UX
    lesson_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'autocomplete': 'off',
        }),
        help_text="Выберите дату занятия"
    )
    
    # Changed to time input instead of dropdowns
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        help_text="Введите время начала (например: 14:30)"
    )
    
    duration_minutes = forms.ChoiceField(
        choices=[
            (45, "45 минут"),
            (60, "1 час"),
            (90, "1.5 часа"),
        ],
        initial=60,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Продолжительность занятия"
    )

    # New: recurrence controls (not stored in model)
    repeat_weekly = forms.BooleanField(
        required=False,
        initial=False,
        label='Повторять еженедельно',
        help_text='Создать копии на следующие недели в тот же день и время'
    )
    repeat_weeks = forms.ChoiceField(
        required=False,
        choices=[(str(i), f"{i}") for i in range(1, 13)],
        initial='4',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Количество недель'
    )

    class Meta:
        model = Lesson
        # Removed description, materials; keep teacher_materials
        fields = ['title', 'subject', 'teacher', 'student', 'teacher_materials', 'zoom_link']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название занятия'}),
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'teacher': forms.Select(attrs={'class': 'form-select'}),
            'student': forms.Select(attrs={'class': 'form-select'}),
            'teacher_materials': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'zoom_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://zoom.us/j/...', 'required': 'required'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['subject'].empty_label = None
        self.fields['teacher'].empty_label = None
        self.fields['student'].empty_label = None

        # Filter teacher and student choices
        self.fields['teacher'].queryset = User.objects.filter(role=User.UserRole.TEACHER, is_active=True)
        self.fields['student'].queryset = User.objects.filter(role=User.UserRole.STUDENT, is_active=True)

        # Initialize form with existing lesson data if editing
        if self.instance and self.instance.pk:
            self.fields['lesson_date'].initial = self.instance.start_time.date()
            self.fields['start_time'].initial = self.instance.start_time.time()
            duration = int((self.instance.end_time - self.instance.start_time).total_seconds() / 60)
            self.fields['duration_minutes'].initial = duration

        # Recurrence controls are only applicable on create; hide on edit visually by help text
        if self.instance and self.instance.pk:
            self.fields['repeat_weekly'].widget = forms.HiddenInput()
            self.fields['repeat_weeks'].widget = forms.HiddenInput()

        self.fields['zoom_link'].required = True

    def clean(self):
        cleaned_data = super().clean()
        lesson_date = cleaned_data.get('lesson_date')
        start_time = cleaned_data.get('start_time')
        duration_minutes = cleaned_data.get('duration_minutes')
        teacher = cleaned_data.get('teacher')
        zoom_link = cleaned_data.get('zoom_link')
        # Получаем таймзону пользователя из данных формы
        user_timezone = self.data.get('user_timezone') or 'UTC'
        if all([lesson_date, start_time, duration_minutes]):
            naive_start = datetime.combine(lesson_date, start_time)
            # Локализуем время в таймзоне пользователя
            try:
                local_start = naive_start.replace(tzinfo=ZoneInfo(user_timezone))
            except Exception:
                local_start = timezone.make_aware(naive_start)
            # Переводим в UTC для сравнения
            start_datetime_utc = local_start.astimezone(ZoneInfo('UTC'))
            end_datetime = local_start + timedelta(minutes=int(duration_minutes))
            cleaned_data['start_datetime'] = local_start
            cleaned_data['end_datetime'] = end_datetime
            # Сравниваем с текущим временем в UTC
            current_time_utc = timezone.now().astimezone(ZoneInfo('UTC'))
            if start_datetime_utc < current_time_utc:
                raise forms.ValidationError(
                    "Нельзя назначить занятие на прошедшее время (по вашему времени устройства)."
                )
            
            # Check for overlapping lessons
            if teacher:
                # Check lessons ending before this one
                previous_lessons = Lesson.objects.filter(
                    teacher=teacher,
                    end_time__lte=start_datetime_utc,
                    status__in=[Lesson.LessonStatus.SCHEDULED, Lesson.LessonStatus.COMPLETED]
                ).exclude(pk=self.instance.pk if self.instance else None).order_by('-end_time')
                
                if previous_lessons.exists():
                    last_lesson_end = previous_lessons.first().end_time
                    if start_datetime_utc - last_lesson_end < timedelta(minutes=15):
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

        if not zoom_link:
            raise forms.ValidationError('Ссылка на занятие обязательна.')

        # Normalize repeat_weeks
        if cleaned_data.get('repeat_weekly'):
            weeks = cleaned_data.get('repeat_weeks') or '4'
            try:
                cleaned_data['repeat_weeks'] = int(weeks)
            except (TypeError, ValueError):
                cleaned_data['repeat_weeks'] = 4
            if cleaned_data['repeat_weeks'] < 1:
                cleaned_data['repeat_weeks'] = 1
            if cleaned_data['repeat_weeks'] > 26:
                cleaned_data['repeat_weeks'] = 26

        return cleaned_data
    
    def save(self, commit=True):
        lesson = super().save(commit=False)
        lesson.start_time = self.cleaned_data['start_datetime']
        lesson.end_time = self.cleaned_data['end_datetime']
        if commit:
            lesson.save()

        return lesson
