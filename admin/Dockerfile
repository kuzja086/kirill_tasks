# Веб-админка навыка: заявки на выполнение, штрафы и история операций.
# Собирать из корня репозитория:
#   docker build -t alice-skill-admin -f admin/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY admin/requirements.txt /app/admin-requirements.txt
RUN pip install --no-cache-dir -r /app/admin-requirements.txt

COPY alice_skill /app/alice_skill
COPY admin /app/admin

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status == 200 else 1)"

CMD ["python", "-m", "admin.serve"]
