#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import requests
import gzip
import io
from lxml import etree
from rapidfuzz import process, fuzz

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Forzar 1080p máximo
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"

# EPGs a usar
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]
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

# ------------------- EPG HANDLING ----------------------
def load_epg(epg_urls):
    epg_channels = {}
    for url in epg_urls:
        try:
            print(f"[INFO] Descargando EPG: {url}")
            r = requests.get(url, timeout=15)
            if url.endswith(".gz"):
                with gzip.open(io.BytesIO(r.content), "rb") as f:
                    content = f.read()
            else:
                content = r.content

            root = etree.fromstring(content)
            for ch in root.findall("channel"):
                tvg_id = ch.get("id")
                display_name = ch.findtext("display-name")
                if tvg_id and display_name:
                    epg_channels[tvg_id] = display_name
        except Exception as e:
            print(f"[WARNING] No se pudo procesar EPG {url}: {e}")
    return epg_channels

def match_channel(epg_channels, title):
    if not epg_channels:
        return None
    names = list(epg_channels.values())
    match, score, _ = process.extractOne(title, names, scorer=fuzz.token_sort_ratio)
    return match if score >= 80 else None

# ------------------- STREAM INFO -----------------------
def get_stream_info(stream_url):
    try:
        auth_opts = get_auth_options(stream_url)

        # Obtener mejor calidad disponible
        cmd = [
            "yt-dlp",
            "-f", FORMAT_SELECTOR,
            "-g", "--no-check-certificate"
        ] + auth_opts + [stream_url]

        url = run_command(cmd)
        if not url:
            return None, None, None, None

        # Título
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"

        # Thumbnail
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [stream_url])

        # ID único
        if "youtu" in stream_url:
            match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", stream_url)
            tvg_id = match.group(1).lower() if match else normalize_id(title)
        else:
            tvg_id = normalize_id(title)

        return url, title, thumbnail, tvg_id

    except Exception:
        return None, None, None, None

# ------------------- GENERAR M3U -----------------------
def generate_m3u(input_path, output_path, epg_channels):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    epg_line = ",".join(EPG_URLS)
    success = 0

    print("[INFO] Generando playlist...")

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        for line in lines:
            url, category = parse_line(line)
            m3u8_url, title, thumbnail, tvg_id = get_stream_info(url)

            if not m3u8_url:
                continue

            # Buscar coincidencia en EPG
            epg_name = match_channel(epg_channels, title)
            final_name = epg_name if epg_name else title

            if thumbnail:
                out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{final_name}\n{m3u8_url}\n')
            else:
                out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{final_name}\n{m3u8_url}\n')

            success += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success} streams agregados correctamente.")

# ------------------- MAIN -----------------------
if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    print("[INFO] Descargando EPG...")
    epg_channels = load_epg(EPG_URLS)

    generate_m3u(INPUT_FILE, OUTPUT_FILE, epg_channels)