FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=10000
CMD ["gunicorn","-b","0.0.0.0:10000","--timeout","600","--workers","1","--threads","1","--access-logfile","-","--error-logfile","-","--capture-output","app:APP"]
