FROM python:3.12-alpine

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN adduser -D -h /app palui

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=palui:palui app ./app
COPY --chown=palui:palui entrypoint.sh ./entrypoint.sh
RUN chown -R palui:palui /app && chmod -R a+rX /app
RUN chmod +x /app/entrypoint.sh

USER palui
EXPOSE 8005

ENTRYPOINT ["/app/entrypoint.sh"]
