FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# La base y las fotos se guardan en volumenes: recrear el contenedor no borra
# el catalogo ni las imagenes subidas.
VOLUME ["/app/data", "/app/app/static/uploads"]

EXPOSE 8515

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8515"]
