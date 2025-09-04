#!/bin/bash

# Verificar si yt-dlp está instalado
echo "Verificando yt-dlp..."
if ! command -v yt-dlp &> /dev/null
then
    echo "[ERROR] yt-dlp no está instalado. Instalalo usando: pip install yt-dlp"
    exit 1
fi

# Ejecutar el script Python
echo "Ejecutando stream_extractor.py..."
python3 stream_extractor.py
