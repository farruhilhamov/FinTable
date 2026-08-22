import csv
import io
import zipfile
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from .spec import get_specs, export_rows, export_all, import_rows


def _csv_response(filename, rows):
    buf = io.StringIO()
    buf.write('\ufeff')  # BOM для корректного открытия в Excel
    writer = csv.writer(buf, delimiter=';')
    for row in rows:
        writer.writerow(row)
    resp = HttpResponse(buf.getvalue().encode('utf-8'), content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


class ImportExportView(LoginRequiredMixin, View):
    template_name = 'importexport/index.html'

    def get(self, request):
        specs = get_specs()
        return render(request, self.template_name, {'specs': specs})

    def post(self, request):
        action = request.POST.get('action')
        specs = get_specs()

        if action == 'export_all':
            buf = BytesIO()
            zf = zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED)
            for key, spec in specs.items():
                rows = export_rows(request.user, spec)
                csv_buf = io.StringIO()
                csv_buf.write('\ufeff')
                writer = csv.writer(csv_buf, delimiter=';')
                for row in rows:
                    writer.writerow(row)
                zf.writestr(f'{key}.csv', csv_buf.getvalue().encode('utf-8'))
            zf.close()
            resp = HttpResponse(buf.getvalue(), content_type='application/zip')
            resp['Content-Disposition'] = 'attachment; filename="fintable_export.zip"'
            return resp

        if action == 'export':
            key = request.POST.get('entity')
            spec = specs.get(key)
            if not spec:
                messages.error(request, 'Неизвестная сущность для экспорта.')
                return render(request, self.template_name, {'specs': specs})
            rows = export_rows(request.user, spec)
            return _csv_response(f'{key}.csv', rows)

        if action == 'import':
            key = request.POST.get('entity')
            spec = specs.get(key)
            upload = request.FILES.get('file')
            if not spec:
                messages.error(request, 'Неизвестная сущность для импорта.')
                return render(request, self.template_name, {'specs': specs})
            if not upload:
                messages.error(request, 'Не выбран файл для импорта.')
                return render(request, self.template_name, {'specs': specs})

            raw = upload.read()
            try:
                decoded = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                decoded = raw.decode('cp1251', errors='replace')
            reader = csv.reader(io.StringIO(decoded), delimiter=';')
            rows = [r for r in reader]
            report = import_rows(request.user, spec, rows)
            messages.info(
                request,
                f'Импорт «{spec.verbose_name}»: создано {report["created"]}, '
                f'обновлено {report["updated"]}, ошибок: {len(report["errors"])}.'
            )
            return render(request, self.template_name, {
                'specs': specs,
                'import_report': report,
                'import_entity': key,
            })

        messages.error(request, 'Неизвестное действие.')
        return render(request, self.template_name, {'specs': specs})
