FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/tmp/dashboard-output

EXPOSE 8080

CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}
