FROM python:3.12-slim
WORKDIR /app
COPY requirements-runtime.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-runtime.txt \
    && pip install --no-deps catboost==1.2.7
COPY app ./app
COPY models ./models
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
