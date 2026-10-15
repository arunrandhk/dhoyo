FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd --system appgroup \
    && useradd --system --gid appgroup appuser

COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    -r requirements.txt

COPY app.py .
COPY db.py .
COPY social.py arena.py geography.py auth.py messages.py friends.py password_reset.py privacy.py organisations.py ./
COPY auth_envelope.py tournament_verification.py tournament_activation.py ./
COPY start.sh .
COPY static ./static

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

CMD ["/bin/sh", "/app/start.sh"]
