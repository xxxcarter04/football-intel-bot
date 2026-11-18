FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY football_intel ./football_intel
COPY README.md .

RUN mkdir -p /app/.data

# Paid Render background worker: Telegram long polling needs no inbound port.
CMD ["python", "-m", "football_intel.bot.main"]
