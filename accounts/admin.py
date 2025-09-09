from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from django.http import HttpRequest
import logging

from .models import User, UserProfile


logger = logging.getLogger('admin_actions')


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "middle_name", "email", "role", "timezone")


class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "middle_name", "email", "role", "timezone", "is_active")


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'


class UserAdmin(BaseUserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    
    list_display = ('username', 'full_name', 'email', 'role', 'timezone', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'created_at')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'middle_name', 'email', 'phone')}),
        (_('Role & Settings'), {'fields': ('role', 'timezone')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
        (_('Created by'), {'fields': ('created_by',)}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'first_name', 'last_name', 'middle_name', 'email', 'role', 'timezone', 'password1', 'password2'),
        }),
    )
    
    inlines = [UserProfileInline]
    
    def save_model(self, request, obj, form, change):
        """
        Override save_model to enforce role-based creation permissions
        and log admin actions
        """
        if not change:  # Creating new user
            if not request.user.is_methodist() and not request.user.is_superuser:
                raise PermissionDenied("Only Methodist can create new users")
            obj.created_by = request.user
            
        # Log the action
        action = "updated" if change else "created"
        logger.info(f"User {request.user.username} {action} user {obj.username} with role {obj.role}")
        
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        """
        Filter queryset based on user role
        Methodist can see all users, others see limited data
        """
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.is_methodist():
            return qs
        # Teachers and students can only see themselves
        return qs.filter(id=request.user.id)
    
    def has_add_permission(self, request):
        """Only Methodist and superuser can add users"""
        return request.user.is_superuser or request.user.is_methodist()
    
    def has_change_permission(self, request, obj=None):
        """Users can edit themselves, Methodist can edit all"""
        if request.user.is_superuser or request.user.is_methodist():
            return True
        if obj and obj == request.user:
            return True
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Only Methodist and superuser can delete users"""
        return request.user.is_superuser or request.user.is_methodist()


admin.site.register(User, UserAdmin)
admin.site.register(UserProfile)

# Customize admin site headers
admin.site.site_header = "Driving School Management"
admin.site.site_title = "Driving School Admin"
admin.site.index_title = "Welcome to Driving School Management"
