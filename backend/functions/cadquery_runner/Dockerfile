FROM python:3.12-slim

# Install system dependencies for CadQuery/OpenCASCADE
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglu1-mesa \
    libxrender1 \
    libxcursor1 \
    libxft2 \
    libxinerama1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-runner.txt .
RUN pip install --no-cache-dir -r requirements-runner.txt

COPY runner.py .

CMD ["python", "runner.py"]
