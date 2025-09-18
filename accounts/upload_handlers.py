from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.conf import settings

class MaxSizeFileUploadHandler(FileUploadHandler):
    """Upload handler that aborts upload if a file exceeds UPLOAD_MAX_FILE_SIZE.
    It tracks the size per file (not whole request)."""

    def __init__(self, request=None):
        super().__init__(request)
        self.max_size = getattr(settings, 'UPLOAD_MAX_FILE_SIZE', 200 * 1024 * 1024)
        self.file_size = 0

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        # reset per-file counter
        self.file_size = 0

    def receive_data_chunk(self, raw_data, start):
        # raw_data is a bytes chunk
        self.file_size += len(raw_data)
        if self.file_size > self.max_size:
            # StopUpload will interrupt the upload; connection_reset True hints to reset
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        # nothing special to return; Django will wrap received chunks into UploadedFile
        return None

