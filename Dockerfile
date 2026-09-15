FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar os navegadores do playwright (embora a imagem base ja traga, garantimos)
RUN playwright install chromium

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
