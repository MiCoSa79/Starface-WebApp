FROM python:3.11-slim
WORKDIR /app

# Build-Argument aus GitHub Actions: Versionsnummer (Datums-Tags entfallen seit F57)
ARG APP_VERSION=unbekannt
ENV APP_VERSION=${APP_VERSION}

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]