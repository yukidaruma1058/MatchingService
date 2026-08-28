FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY api/app /app/app
COPY batch/app /batch/app
COPY batch/BAT-002 /batch/BAT-002
COPY batch/BAT-003 /batch/BAT-003
COPY batch/BAT-006 /batch/BAT-006

ENV BATCH_ROOT=/batch \
    BATCH_LOG_PATH=/app/log/batch.log

RUN mkdir -p /app/log

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
