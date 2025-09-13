import os
import sys
import django

# Ensure the project directory is in sys.path
project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_path not in sys.path:
    sys.path.insert(0, project_path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'driving_school.settings')
django.setup()

from scheduling.models import Lesson, LessonFile

out_lines = []
out_lines.append('Lessons total: ' + str(Lesson.objects.count()))
for lesson in Lesson.objects.all():
    out_lines.append(f"Lesson {lesson.id}: {lesson.title!r}, teacher_materials present={bool(lesson.teacher_materials)}")
    lfs = LessonFile.objects.filter(lesson=lesson)
    out_lines.append('  LessonFile count: ' + str(lfs.count()))
    for lf in lfs:
        out_lines.append(f"   LF: {lf.id} | original_name={lf.original_name} | is_teacher_material={lf.is_teacher_material} | file={lf.file.name}")

# write to file
with open('scripts/inspect_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out_lines))

print('WROTE scripts/inspect_output.txt')
