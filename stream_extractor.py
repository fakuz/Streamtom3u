#!/usr/bin/env python3
import os
import sys
import subprocess
import re
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===================== CONFIGURACIÓN =====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"
FALLBACK_URL = "https://raw.githubusercontent.com/fakuz/Streamtom3u/refs/heads/main/fallback/fallback.m3u8"

# Formato preferido
FORMAT_SELECTOR = "bestvideo[height<=1080][vcodec^=avc]+bestaudio/best"

# Instancias Piped / Invidious (para resolver sin cookies)
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks", "https://pipedapi.adminforge.de",
    "https://pipedapi.r4fo.com", "https://pipedapi.in.projectsegfau.lt",
    "https://pipedapi.mha.fi"
]
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net", "https://invidious.flokinet.to",
    "https://invidious.snopyta.org", "https://invidious.nerdvpn.de"
]

MAX_THREADS = 10
REQUEST_TIMEOUT = 15
YT_DLP_TIMEOUT = 20
PROXIES_FILE = "proxies.txt"
# ==========================================================

def load_proxies():
    if os.path.exists(PROXIES_FILE):
        with open(PROXIES_FILE, "r", encoding="utf-8") as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies
    return []

PROXIES = load_proxies()

def random_proxy():
    if PROXIES:
        proxy = random.choice(PROXIES)
        return {"http": proxy, "https": proxy}
    return None

def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado.")
        return False

def parse_line(line):
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category

def get_ytdlp_stream(url):
    """Intenta obtener URL usando yt-dlp con timeout."""
    try:
        result = subprocess.run(
            ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate", url],
            capture_output=True,
            text=True,
            timeout=YT_DLP_TIMEOUT
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"[ERROR] yt-dlp tardó demasiado para: {url}")
    return None

def get_api_stream(url):
    """Intenta obtener URL usando Piped o Invidious con timeout."""
    video_id_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", url)
    if not video_id_match:
        return None
    video_id = video_id_match.group(1)

    # Probar Piped
    for instance in random.sample(PIPED_INSTANCES, len(PIPED_INSTANCES)):
        api_url = f"{instance}/streams/{video_id}"
        try:
            r = requests.get(api_url, timeout=REQUEST_TIMEOUT, proxies=random_proxy())
            if r.status_code == 200:
                data = r.json()
                if "hls" in data and data["hls"]:
                    return data["hls"]
        except requests.RequestException:
            continue

    # Probar Invidious
    for instance in random.sample(INVIDIOUS_INSTANCES, len(INVIDIOUS_INSTANCES)):
        api_url = f"{instance}/api/v1/videos/{video_id}"
        try:
            r = requests.get(api_url, timeout=REQUEST_TIMEOUT, proxies=random_proxy())
            if r.status_code == 200:
                data = r.json()
                if "adaptiveFormats" in data:
                    for f in data["adaptiveFormats"]:
                        if "hlsManifestUrl" in f:
                            return f["hlsManifestUrl"]
        except requests.RequestException:
            continue

    return None

def get_stream_info(line):
    url, category = parse_line(line)
    stream_url = None

    # 1. Intentar API Piped / Invidious
    stream_url = get_api_stream(url)

    # 2. Si falla, intentar yt-dlp
    if not stream_url:
        stream_url = get_ytdlp_stream(url)

    # 3. Si todo falla, usar fallback
    if not stream_url:
        print(f"[WARNING] No se pudo obtener stream de: {url}. Usando fallback.")
        stream_url = FALLBACK_URL

    # Nombre del canal = texto antes del primer "|" en links.txt
    title = url.split("://")[-1].split("/")[0] if "|" not in line else line.split("|")[0]

    # ID único
    tvg_id = re.sub(r'[^a-z0-9]', '', title.lower())

    return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{stream_url}\n'

def generate_m3u():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] No se encontró el archivo: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    print(f"[CONFIG] Fallback: {FALLBACK_URL}")
    print(f"[CONFIG] Piped: {len(PIPED_INSTANCES)} instancias | Invidious: {len(INVIDIOUS_INSTANCES)} instancias")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("#EXTM3U\n")
        success_count = 0

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_line = {executor.submit(get_stream_info, line): line for line in lines}
            for future in as_completed(future_to_line):
                out.write(future.result())
                success_count += 1

    print(f"\n✅ Archivo M3U generado: {OUTPUT_FILE}")
    print(f"✔ {success_count} streams procesados (Piped → Invidious → yt-dlp → fallback).")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)
    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")
    generate_m3u()