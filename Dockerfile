FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    TZ=America/Chicago \
    DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/

EXPOSE 8080

VOLUME ["/data"]

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "--timeout", "120", "main:app"]
