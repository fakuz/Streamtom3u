#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import gzip
import requests
from io import BytesIO
from lxml import etree
from rapidfuzz import process
from concurrent.futures import ThreadPoolExecutor

# ==================== CONFIG ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"

EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]
# =================================================

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

def fetch_epg(url):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.content
        if url.endswith(".gz"):
            data = gzip.decompress(data)
        return data
    except:
        return None

def load_epg():
    print("[INFO] Descargando EPG...")
    epg_channels = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = executor.map(fetch_epg, EPG_URLS)

    for data in results:
        if not data:
            continue
        try:
            root = etree.parse(BytesIO(data))
            for channel in root.xpath("//channel"):
                tvg_id = channel.get("id") or ""
                display_names = channel.xpath("display-name/text()")
                if display_names:
                    epg_channels[display_names[0].strip()] = {
                        "id": tvg_id,
                        "names": display_names
                    }
        except:
            continue

    return epg_channels

def find_best_match(title, epg_channels):
    if not epg_channels:
        return None, None
    names = list(epg_channels.keys())
    best_match = process.extractOne(title, names, score_cutoff=75)
    if best_match:
        name = best_match[0]
        return name, epg_channels[name]["id"]
    return None, None

def get_stream_info(stream_url, epg_channels):
    try:
        auth_opts = get_auth_options(stream_url)

        # Obtener la mejor URL
        url = run_command(["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"] + auth_opts + [stream_url])
        if not url:
            return None, None, None, None

        # Título original
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"

        # Thumbnail
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [stream_url])

        # Match con EPG
        epg_name, epg_id = find_best_match(title, epg_channels)

        final_title = epg_name if epg_name else title
        tvg_id = epg_id if epg_id else normalize_id(title)

        return url, final_title, thumbnail, tvg_id

    except:
        return None, None, None, None

def generate_m3u(input_path, output_path, epg_channels):
    if not os.path.exists(input_path):
        print("[ERROR] No se encontró el archivo:", input_path)
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    print("[INFO] Generando playlist...")
    success, fail = 0, 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{",".join(EPG_URLS)}"\n')
        for line in lines:
            url, category = parse_line(line)
            m3u8_url, title, thumbnail, tvg_id = get_stream_info(url, epg_channels)
            if m3u8_url:
                logo = f' tvg-logo="{thumbnail}"' if thumbnail else ""
                out.write(f'#EXTINF:-1 tvg-id="{tvg_id}"{logo} group-title="{category}",{title}\n{m3u8_url}\n')
                success += 1
            else:
                fail += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success} streams agregados correctamente.")
    if fail:
        print(f"⚠ {fail} enlaces fallaron.")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    epg_channels = load_epg()
    generate_m3u(INPUT_FILE, OUTPUT_FILE, epg_channels)