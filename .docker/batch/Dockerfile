FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY batch/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY .docker/batch/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY batch/app /app/app
COPY batch/BAT-001 /app/BAT-001
COPY batch/BAT-002 /app/BAT-002
COPY batch/BAT-003 /app/BAT-003
COPY batch/BAT-006 /app/BAT-006

ENV PYTHONPATH=/app

ENTRYPOINT ["/entrypoint.sh"]
CMD []
