FROM python:3.13-slim

# Install git (required by GitPython), ffmpeg, and Node.js for frontend build
RUN apt-get update && apt-get install -y git ffmpeg curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Frontend build
COPY frontend/package.json frontend/package-lock.json* frontend/
RUN cd frontend && npm install
COPY frontend/ frontend/
RUN cd frontend && npm run build

# Copy backend source
COPY main.py .
COPY src/ src/

CMD ["python", "main.py"]
