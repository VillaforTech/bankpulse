FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY adapter.py /app/adapter.py

RUN addgroup -S bankpulse && adduser -S -G bankpulse -u 10001 bankpulse \
    && mkdir -p /data && chown bankpulse:bankpulse /data

USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/adapter.py"]
