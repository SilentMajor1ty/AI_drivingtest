from django import template

register = template.Library()

@register.filter
def notification_type_color(notification_type):
    """Return Bootstrap color class for notification type"""
    color_map = {
        'lesson_created': 'success',
        'lesson_updated': 'info',
        'lesson_reminder_24h': 'warning',
        'lesson_reminder_1h': 'danger',
        'assignment_assigned': 'primary',
        'assignment_due_soon': 'warning',
        'assignment_overdue': 'danger',
        'assignment_submitted': 'info',
        'assignment_reviewed': 'success',
    }
    return color_map.get(notification_type, 'secondary')

@register.filter
def notification_type_icon(notification_type):
    """Return Bootstrap icon for notification type"""
    icon_map = {
        'lesson_created': 'calendar-plus',
        'lesson_updated': 'calendar-event',
        'lesson_reminder_24h': 'clock',
        'lesson_reminder_1h': 'exclamation-triangle',
        'assignment_assigned': 'journal-plus',
        'assignment_due_soon': 'clock-history',
        'assignment_overdue': 'exclamation-triangle',
        'assignment_submitted': 'check-circle',
        'assignment_reviewed': 'star',
    }
    return icon_map.get(notification_type, 'bell')