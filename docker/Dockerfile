# Image unique d'EasyMaint, identique pour l'installation locale et le SaaS.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
ARG REQUIREMENTS=base
RUN pip install -r requirements/${REQUIREMENTS}.txt

COPY . .

# Bootstrap, HTMX et Chart.js sont téléchargés une fois à la construction :
# l'application fonctionne ensuite sans Internet (réseau local de l'usine).
RUN sh scripts/vendor_static.sh

# Traductions : contrôle des fichiers .po (formats %(...)s identiques) et compilation en .mo.
RUN for po in locale/*/LC_MESSAGES/django.po; do msgfmt --check -o "${po%.po}.mo" "$po" || exit 1; done

RUN useradd --create-home --uid 1000 easymaint \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R easymaint:easymaint /app
USER easymaint

EXPOSE 8000
ENTRYPOINT ["sh", "docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
