FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt psycopg[binary]
COPY backend ./backend
COPY benchmarks ./benchmarks
ENV PYTHONPATH=/app/backend AGENTEVALOPS_DATABASE_URL=sqlite:////app/artifacts/agentevalops.db
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
