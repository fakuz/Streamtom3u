#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import json
import urllib.request
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Forzar máximo 1080p
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"

# Lista de EPGs
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]

# URL del JSON de canales oficiales
CHANNELS_JSON_URL = "https://iptv-org.github.io/api/channels.json"
CHANNELS_FILE = "channels.json"

# Palabras irrelevantes en títulos
IGNORE_WORDS = ["latino", "hd", "oficial", "tv", "canal", "channel"]

# Mapeo de categorías para fallback
CATEGORY_MAP = {
    "películas": "Movies",
    "cine": "Movies",
    "deportes": "Sports",
    "noticias": "News",
    "infantil": "Kids",
    "música": "Music"
}

# Número de hilos para paralelismo
MAX_WORKERS = 8
# =======================================================

def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado.")
        return False

def cookies_valid():
    return (
        os.path.exists("cookies.txt")
        and os.path.getsize("cookies.txt") > 100
        and open("cookies.txt", "r", encoding="utf-8").readline().strip().startswith("# Netscape")
    )

def get_auth_options(url):
    if cookies_valid() and ("youtube.com" in url or "youtu.be" in url or "facebook.com" in url):
        return ["--cookies", "cookies.txt"]
    return []

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    """Devuelve (url, categoria) desde la línea del archivo."""
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category

def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        urllib.request.urlretrieve(CHANNELS_JSON_URL, CHANNELS_FILE)
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

CHANNELS = load_channels()

def clean_name(name):
    name = name.lower()
    for word in IGNORE_WORDS:
        name = name.replace(word, "")
    return re.sub(r'[^a-z0-9 ]', '', name).strip()

def find_epg_match(title, category):
    cleaned_title = clean_name(title)
    best_match = None
    best_score = 0

    # Intento 1: Coincidencia difusa por nombre
    for channel in CHANNELS:
        channel_name = clean_name(channel["name"])
        score = difflib.SequenceMatcher(None, cleaned_title, channel_name).ratio()
        if score > best_score:
            best_score = score
            best_match = channel

    if best_match and best_score >= 0.8:
        return best_match["id"], best_match["name"], best_match["logo"]

    # Intento 2: Fallback por categoría
    for key, mapped_cat in CATEGORY_MAP.items():
        if key in category.lower():
            for channel in CHANNELS:
                if channel.get("category", "").lower() == mapped_cat.lower():
                    return channel["id"], channel["name"], channel["logo"]
            break

    return None, None, None

def get_stream_info(line):
    url, category = parse_line(line)
    try:
        auth_opts = get_auth_options(url)

        # URL del stream en máxima calidad (1080p máx)
        cmd = [
            "yt-dlp",
            "-f", FORMAT_SELECTOR,
            "-g", "--no-check-certificate"
        ] + auth_opts + [url]

        m3u8_url = run_command(cmd)
        if not m3u8_url:
            return None

        # Título
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [url]) or "Stream"

        # Intentar match con EPG
        epg_id, epg_name, epg_logo = find_epg_match(title, category)

        if epg_id and epg_name:
            tvg_id = epg_id
            title = epg_name
            logo = epg_logo
        else:
            tvg_id = normalize_id(title)
            logo = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [url])

        return {
            "m3u8_url": m3u8_url,
            "title": title,
            "logo": logo,
            "tvg_id": tvg_id,
            "category": category
        }

    except Exception:
        return None

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    success, fail = 0, 0
    epg_line = ",".join(EPG_URLS)

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_stream_info, line): line for line in lines}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
                success += 1
            else:
                fail += 1

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        for r in results:
            if r["logo"]:
                out.write(f'#EXTINF:-1 tvg-id="{r["tvg_id"]}" tvg-logo="{r["logo"]}" group-title="{r["category"]}",{r["title"]}\n{r["m3u8_url"]}\n')
            else:
                out.write(f'#EXTINF:-1 tvg-id="{r["tvg_id"]}" group-title="{r["category"]}",{r["title"]}\n{r["m3u8_url"]}\n')

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success} streams agregados correctamente.")
    if fail > 0:
        print(f"⚠ {fail} enlaces fallaron.")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    generate_m3u(INPUT_FILE, OUTPUT_FILE)