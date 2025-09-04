#!/usr/bin/env python3
import subprocess
import os
import sys

INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado o no está en el PATH.")
        return False

def get_stream_info(stream_url):
    """Obtiene URL M3U8 y título del stream con manejo de errores."""
    try:
        # Extraer la mejor URL
        result = subprocess.run(
            ["yt-dlp", "-f", "best", "-g", stream_url],
            capture_output=True,
            text=True
        )

        if result.returncode != 0 or not result.stdout.strip():
            print(f"[ERROR] No se pudo obtener URL para: {stream_url}")
            print("[yt-dlp stderr]:", result.stderr)
            return None, None

        url = result.stdout.strip()

        # Obtener título
        title_result = subprocess.run(
            ["yt-dlp", "--get-title", stream_url],
            capture_output=True,
            text=True
        )

        title = title_result.stdout.strip() if title_result.returncode == 0 else "Desconocido"
        return url, title

    except Exception as e:
        print(f"[EXCEPTION] Error procesando {stream_url}: {e}")
        return None, None

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip()]

    if not links:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("#EXTM3U\n")
        for link in links:
            print(f"[INFO] Procesando: {link}")
            m3u8_url = get_m3u8_url(link)
            if m3u8_url:
                out.write(f"#EXTINF:-1,{link}\n{m3u8_url}\n")
            else:
                print(f"[WARNING] No se pudo obtener M3U8 de: {link}")

    print(f"\n✅ Archivo M3U generado correctamente: {output_path}")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)
    generate_m3u(INPUT_FILE, OUTPUT_FILE)
