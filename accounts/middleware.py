from django.utils import timezone as dj_timezone
from django.utils.deprecation import MiddlewareMixin

class UserTimezoneMiddleware(MiddlewareMixin):
    """Активирует таймзону пользователя или обнаруженную в сессии.
    Приоритет: session['detected_timezone'] > user.timezone > UTC.
    """
    def process_request(self, request):
        tz_name = None
        # 1. Session detected timezone
        tz_name = request.session.get('detected_timezone')
        # 2. Fallback to user profile
        if not tz_name and getattr(request, 'user', None) and request.user.is_authenticated:
            tz_name = getattr(request.user, 'timezone', None)
        try:
            if tz_name:
                dj_timezone.activate(tz_name)
            else:
                dj_timezone.deactivate()  # будет UTC
        except Exception:
            dj_timezone.deactivate()

    def process_response(self, request, response):
        # Явно отключать не нужно, Django сам сбрасывает локально.
        return response

