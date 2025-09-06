#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIG ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

PIPED_APIS = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.syncpundit.io",
    "https://pipedapi.r4fo.com",
    "https://pipedapi.in.projectsegfau.lt"
]

FALLBACK_URL = "https://raw.githubusercontent.com/fakuz/Streamtom3u/refs/heads/main/fallback/fallback.m3u8"
MAX_THREADS = 10
# =================================================

def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado.")
        return False

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    parts = [p.strip() for p in line.split("|")]
    url = parts[0]
    category = parts[1] if len(parts) > 1 and parts[1] else "General"
    channel_name = parts[2] if len(parts) > 2 and parts[2] else url
    return url, category, channel_name

def extract_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", url)
    return match.group(1) if match else None

def get_youtube_stream(video_id):
    for api in PIPED_APIS:
        try:
            r = requests.get(f"{api}/streams/{video_id}", timeout=8)
            if r.status_code == 200:
                data = r.json()
                if data.get("hls"):
                    return data["hls"]
                if data.get("dash"):
                    return data["dash"]
        except Exception:
            continue
    return None

def get_yt_dlp_stream(url, use_cookies=False):
    try:
        cmd = ["yt-dlp", "-f", "b", "-g", "--no-check-certificate"]
        if use_cookies and os.path.exists("cookies.txt"):
            cmd += ["--cookies", "cookies.txt"]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None

def get_stream_info(line):
    url, category, channel_name = parse_line(line)
    tvg_id = normalize_id(channel_name)
    stream_url = None

    # 1. Intentar Piped (solo para YouTube)
    if "youtube.com" in url or "youtu.be" in url:
        video_id = extract_video_id(url)
        if video_id:
            stream_url = get_youtube_stream(video_id)

    # 2. Intentar yt-dlp sin cookies
    if not stream_url:
        stream_url = get_yt_dlp_stream(url, use_cookies=False)

    # 3. Intentar yt-dlp con cookies
    if not stream_url and os.path.exists("cookies.txt"):
        stream_url = get_yt_dlp_stream(url, use_cookies=True)

    # 4. Si todo falla, fallback
    if not stream_url:
        print(f"[WARNING] No se pudo obtener stream de: {url}. Usando fallback.")
        stream_url = FALLBACK_URL

    return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{channel_name}\n{stream_url}\n'

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    success_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="https://iptv-org.github.io/epg/guides/es.xml"\n')

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_line = {executor.submit(get_stream_info, line): line for line in lines}
            for future in as_completed(future_to_line):
                result = future.result()
                if result:
                    out.write(result)
                    success_count += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success_count} streams procesados (con fallback si falló).")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    generate_m3u(INPUT_FILE, OUTPUT_FILE)