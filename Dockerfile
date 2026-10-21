FROM python:3.12.7-slim
WORKDIR /app
COPY app.py scoring.py ./
COPY web ./web
RUN useradd --uid 10001 --create-home app && mkdir /app/data && chown app:app /app/data
USER app
ENV HOST=0.0.0.0 PORT=8000 DB_PATH=/app/data/credit.db PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "app.py"]
