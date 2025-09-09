from django import forms
from .models import Lesson, Subject
from accounts.models import User


class LessonForm(forms.ModelForm):
    """Form for creating and updating lessons"""
    
    class Meta:
        model = Lesson
        fields = ['title', 'subject', 'teacher', 'student', 'start_time', 'end_time', 'description', 'zoom_link']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'teacher': forms.Select(attrs={'class': 'form-select'}),
            'student': forms.Select(attrs={'class': 'form-select'}),
            'start_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'zoom_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://zoom.us/j/...'})
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter teacher and student choices
        self.fields['teacher'].queryset = User.objects.filter(role=User.UserRole.TEACHER)
        self.fields['student'].queryset = User.objects.filter(role=User.UserRole.STUDENT)