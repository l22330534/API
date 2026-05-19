FROM python:3.10-slim

WORKDIR /app

# Copiamos todo el contenido actual al contenedor
COPY . /app

# Instalamos fastapi, uvicorn y agregamos pydantic (que fastapi usa internamente)
RUN pip install --no-cache-dir fastapi uvicorn pydantic

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]