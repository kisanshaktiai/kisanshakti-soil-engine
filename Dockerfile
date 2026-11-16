FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
COPY soil_ingestion/requirements.txt ./soil_ingestion/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY soil_ingestion ./soil_ingestion
RUN useradd --uid 10001 --create-home soil
USER soil
CMD ["python", "-m", "soil_ingestion.worker"]
