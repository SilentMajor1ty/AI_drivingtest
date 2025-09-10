from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User


class UserCreateForm(UserCreationForm):
    """Form for creating new users"""
    
    class Meta:
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name', 'middle_name',
            'role', 'phone'
        )
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': 'form-control'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control'})
        
        # Restrict role choices for Methodist users - they cannot create other Methodists
        if user and user.is_methodist():
            self.fields['role'].choices = [
                (User.UserRole.STUDENT, User.UserRole.STUDENT.label),
                (User.UserRole.TEACHER, User.UserRole.TEACHER.label),
            ]


class UserUpdateForm(forms.ModelForm):
    """Form for updating existing users"""
    
    class Meta:
        model = User
        fields = (
            'username', 'email', 'first_name', 'last_name', 'middle_name',
            'role', 'phone', 'is_active'
        )
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }