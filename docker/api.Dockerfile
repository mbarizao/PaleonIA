FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Torch e torchvision saem do mesmo índice de CPU. O PyPI mistura um
# torchvision incompatível e o Kraken falha com torchvision::nms.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && python -c "from torchvision.ops import nms"

COPY paleonia paleonia
COPY public public
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PALEONIA_HOST=0.0.0.0 \
    PALEONIA_PORT=8878 \
    PALEONIA_WORK_DIR=/data \
    PALEONIA_OPEN_BROWSER=false \
    KRAKEN_DEVICE=cpu

EXPOSE 8878
VOLUME ["/data"]

ENTRYPOINT ["/entrypoint.sh"]
