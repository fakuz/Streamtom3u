#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import requests
import gzip
import xml.etree.ElementTree as ET
from rapidfuzz import process, fuzz

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"

EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]
# =======================================================

# Cache EPG
epg_channels = {}

def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado.")
        return False

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category

def download_epg():
    global epg_channels
    print("[INFO] Cargando EPG...")
    for epg_url in EPG_URLS:
        try:
            print(f"[INFO] Descargando: {epg_url}")
            r = requests.get(epg_url, timeout=20)
            r.raise_for_status()

            if epg_url.endswith(".gz"):
                data = gzip.decompress(r.content).decode("utf-8", errors="ignore")
            else:
                data = r.text

            root = ET.fromstring(data)
            for ch in root.findall("channel"):
                cid = ch.get("id", "").strip().lower()
                name_tag = ch.find("display-name")
                if cid and name_tag is not None:
                    epg_channels[cid] = name_tag.text.strip()

            print(f"[INFO] EPG cargado ({len(epg_channels)} canales acumulados)")
        except Exception:
            print(f"[WARNING] No se pudo procesar: {epg_url}")

def match_epg_name(tvg_id, title):
    if not epg_channels:
        return title

    query = title.lower()
    match = process.extractOne(query, epg_channels.values(), scorer=fuzz.token_sort_ratio)

    if match and match[1] >= 75:
        return match[0]
    return title

def get_stream_info(stream_url):
    try:
        cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate", stream_url]
        url = run_command(cmd)
        if not url:
            return None, None, None, None

        title = run_command(["yt-dlp", "--get-title", stream_url]) or "Stream"
        thumbnail = run_command(["yt-dlp", "--get-thumbnail", stream_url])
        tvg_id = normalize_id(title)
        return url, title, thumbnail, tvg_id
    except:
        return None, None, None, None

def generate_m3u():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] No se encontró {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{",".join(EPG_URLS)}"\n')
        for line in lines:
            url, category = parse_line(line)
            m3u8_url, title, thumbnail, tvg_id = get_stream_info(url)
            if m3u8_url:
                new_title = match_epg_name(tvg_id, title)
                if thumbnail:
                    out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{new_title}\n{m3u8_url}\n')
                else:
                    out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{new_title}\n{m3u8_url}\n')

    print(f"✅ Archivo M3U generado: {OUTPUT_FILE}")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)
    download_epg()
    generate_m3u()