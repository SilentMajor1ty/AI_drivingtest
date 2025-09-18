from django import forms
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Assignment, AssignmentSubmission
from accounts.models import User


class AssignmentForm(forms.ModelForm):
    """Form for creating assignments without lesson binding"""
    
    # Due date with predefined choices
    DEADLINE_CHOICES = [
        (1, "1 день"),
        (3, "3 дня"), 
        (7, "1 неделя"),
        (14, "2 недели"),
        (21, "3 недели"),
        (30, "1 месяц"),
        (60, "2 месяца"),
    ]
    
    due_date_days = forms.ChoiceField(
        choices=DEADLINE_CHOICES,
        initial=7,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Выберите срок выполнения задания"
    )
    
    class Meta:
        model = Assignment
        # Removed 'lesson' field to eliminate lesson binding
        fields = ['title', 'description', 'student', 'assignment_file']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите название задания'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Подробное описание задания (необязательно)'
            }),
            'student': forms.Select(attrs={'class': 'form-select'}),
            'assignment_file': forms.FileInput(attrs={'class': 'form-control'})
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter students
        self.fields['student'].queryset = User.objects.filter(role=User.UserRole.STUDENT, is_active=True)

        # If editing existing assignment, set the days based on current due_date
        if self.instance and self.instance.pk and self.instance.due_date:
            current_time = timezone.now()
            days_difference = (self.instance.due_date.date() - current_time.date()).days
            
            # Find closest match to existing due date
            closest_choice = min(self.DEADLINE_CHOICES, 
                               key=lambda x: abs(x[0] - days_difference))
            self.fields['due_date_days'].initial = closest_choice[0]
    
    def clean(self):
        cleaned_data = super().clean()
        due_date_days = cleaned_data.get('due_date_days')
        
        if due_date_days:
            # Calculate due date from current time + selected days
            due_date = timezone.now() + timedelta(days=int(due_date_days))
            cleaned_data['calculated_due_date'] = due_date
        
        return cleaned_data
    
    def save(self, commit=True):
        assignment = super().save(commit=False)
        
        # Set calculated due date
        assignment.due_date = self.cleaned_data['calculated_due_date']
        
        # Since we removed lesson binding, we need a way to still track assignments
        # For now, we'll set lesson to None or handle this differently
        if not hasattr(assignment, 'lesson') or assignment.lesson is None:
            # Create a virtual lesson or handle assignments without lesson binding
            # For this implementation, we'll make lesson optional in the model
            pass
            
        if commit:
            assignment.save()
        return assignment


class AssignmentSubmissionForm(forms.ModelForm):
    """Form for students to submit assignments"""
    
    class Meta:
        model = AssignmentSubmission
        fields = ['submission_file', 'comments']
        widgets = {
            'submission_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.txt,.jpg,.png,.zip'
            }),
            'comments': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Комментарии к работе (необязательно)'
            })
        }