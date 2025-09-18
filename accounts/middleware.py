from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone as dj_timezone
from django.utils.deprecation import MiddlewareMixin


class UploadSizeLimitMiddleware(MiddlewareMixin):
    """Reject requests where Content-Length exceeds configured UPLOAD_MAX_FILE_SIZE.
    This is a quick early check to avoid accepting huge uploads. Note: chunked uploads
    without Content-Length won't be caught here, so we also provide an upload handler.
    """
    def process_request(self, request):
        try:
            cl = request.META.get('CONTENT_LENGTH')
            if cl:
                if int(cl) > getattr(settings, 'UPLOAD_MAX_FILE_SIZE', 200 * 1024 * 1024):
                    return HttpResponse('Request Entity Too Large', status=413)
        except (ValueError, TypeError):
            # Unable to parse Content-Length; continue to upload handlers for enforcement
            pass
        return None


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
