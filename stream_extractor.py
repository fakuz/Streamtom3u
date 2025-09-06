#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Fallback fijo si el stream falla
FALLBACK_STREAM = "https://raw.githubusercontent.com/fakuz/Streamtom3u/refs/heads/main/fallback/fallback.m3u8"

# EPG URLs
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml"
]

# API para obtener HLS de YouTube
PIPED_API = "https://piped.video/streams/"

# Número máximo de hilos
MAX_THREADS = 10
# =======================================================

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    """Devuelve (url, categoria, canal) desde la línea del archivo."""
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    channel = parts[2].strip() if len(parts) > 2 else None
    return url, category, channel

def get_youtube_stream(video_id):
    """Obtiene el link HLS desde la API Piped."""
    try:
        response = requests.get(PIPED_API + video_id, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "hls" in data and data["hls"]:
                return data["hls"]
        return None
    except Exception:
        return None

def extract_youtube_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", url)
    return match.group(1) if match else None

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def get_stream_info(line):
    url, category, channel_name = parse_line(line)

    try:
        if "youtube.com" in url or "youtu.be" in url:
            video_id = extract_youtube_id(url)
            if video_id:
                hls_url = get_youtube_stream(video_id)
                title = channel_name or f"YouTube-{video_id}"
                if hls_url:
                    return f'#EXTINF:-1 tvg-id="{video_id}" group-title="{category}",{title}\n{hls_url}\n'
                else:
                    print(f"[WARNING] YouTube API no devolvió HLS para: {url}. Usando fallback.")
                    return f'#EXTINF:-1 tvg-id="{video_id}" group-title="{category}",{title} (OFF AIR)\n{FALLBACK_STREAM}\n'
            else:
                print(f"[ERROR] No se pudo extraer ID de YouTube en: {url}")
                return None

        else:
            # Para Twitch u otros enlaces (usa yt-dlp)
            stream_url = run_command([
                "yt-dlp", "-f", "bv*[height<=1080][vcodec*=avc1]+bestaudio/best",
                "-g", "--no-check-certificate", url
            ])
            title = channel_name or run_command(["yt-dlp", "--get-title", url]) or "Stream"
            tvg_id = normalize_id(title)

            if stream_url:
                return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{stream_url}\n'
            else:
                print(f"[WARNING] No se pudo obtener M3U8 de: {url}. Usando fallback.")
                return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title} (OFF AIR)\n{FALLBACK_STREAM}\n'

    except Exception:
        title_display = (channel_name or "Stream") + " (OFF AIR)"
        return f'#EXTINF:-1 group-title="{category}",{title_display}\n{FALLBACK_STREAM}\n'

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    epg_line = ",".join(EPG_URLS)
    success_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_line = {executor.submit(get_stream_info, line): line for line in lines}
            for future in as_completed(future_to_line):
                result = future.result()
                if result:
                    out.write(result)
                    success_count += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success_count} streams agregados (con fallback si falló).")

if __name__ == "__main__":
    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    print(f"[CONFIG] Fallback: {FALLBACK_STREAM}")
    print(f"[CONFIG] API YouTube: {PIPED_API}")
    generate_m3u(INPUT_FILE, OUTPUT_FILE)