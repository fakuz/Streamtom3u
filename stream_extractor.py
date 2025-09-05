#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import requests
import gzip
import io
from concurrent.futures import ThreadPoolExecutor
from lxml import etree
from rapidfuzz import process, fuzz

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"
THREADS = 5

# Forzar calidad 1080p máximo
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"

# URLs de EPG (pueden incluir .gz)
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]
# =======================================================

epg_channels = {}

# ---------------------- UTILIDADES ----------------------

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def normalize_name(name):
    return re.sub(r'[^a-z0-9 ]', '', name.lower())

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

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

# ---------------------- EPG ----------------------

def load_epg():
    global epg_channels
    print("[INFO] Cargando EPG...")
    for url in EPG_URLS:
        try:
            print(f"[INFO] Descargando EPG: {url}")
            response = requests.get(url, timeout=15)
            response.raise_for_status()

            # Descomprimir si es .gz
            if url.endswith(".gz"):
                with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as f:
                    xml_data = f.read()
            else:
                xml_data = response.content

            root = etree.fromstring(xml_data)
            for channel in root.findall("channel"):
                channel_id = channel.get("id")
                display_name = channel.findtext("display-name")
                if channel_id and display_name:
                    epg_channels[normalize_id(channel_id)] = display_name

            print(f"[INFO] EPG procesado: {url} ({len(epg_channels)} canales acumulados)")

        except Exception as e:
            print(f"[ERROR] No se pudo procesar EPG: {url} -> {e}")

def match_epg_name(original_name):
    """Busca el nombre más parecido en EPG usando tvg-id, parcial y fuzzy"""
    if not epg_channels:
        return original_name

    norm_original = normalize_name(original_name)

    # 1. Match exacto por tvg-id
    for tvg_id, epg_name in epg_channels.items():
        if tvg_id == normalize_id(original_name):
            return epg_name

    # 2. Match parcial por palabras clave
    for tvg_id, epg_name in epg_channels.items():
        if any(word in tvg_id for word in norm_original.split()):
            return epg_name

    # 3. Fuzzy match
    epg_names = list(epg_channels.values())
    best_match = process.extractOne(
        norm_original,
        [normalize_name(n) for n in epg_names],
        scorer=fuzz.token_sort_ratio
    )

    if best_match and best_match[1] >= 40:
        idx = [normalize_name(n) for n in epg_names].index(best_match[0])
        return epg_names[idx]

    return original_name

# ---------------------- STREAM ----------------------

def parse_line(line):
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category

def get_stream_info(stream_url):
    try:
        auth_opts = get_auth_options(stream_url)

        # Obtener URL de stream
        cmd = [
            "yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"
        ] + auth_opts + [stream_url]
        url = run_command(cmd)
        if not url:
            return None, None, None, None

        # Título original
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"

        # Thumbnail
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [stream_url])

        # ID único
        tvg_id = normalize_id(title)

        return url, title, thumbnail, tvg_id

    except Exception:
        return None, None, None, None

def process_stream(line):
    url, category = parse_line(line)
    m3u8_url, title, thumbnail, tvg_id = get_stream_info(url)
    if not m3u8_url:
        return None

    # Forzar nombre al oficial del EPG (si existe)
    final_name = match_epg_name(title)

    if thumbnail:
        return f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{final_name}" tvg-logo="{thumbnail}" group-title="{category}",{final_name}\n{m3u8_url}'
    else:
        return f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{final_name}" group-title="{category}",{final_name}\n{m3u8_url}'

# ---------------------- GENERADOR ----------------------

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
    results = []

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        for result in executor.map(process_stream, lines):
            if result:
                results.append(result)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        for entry in results:
            out.write(entry + "\n")

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {len(results)} streams agregados correctamente.")

# ---------------------- MAIN ----------------------

if __name__ == "__main__":
    load_epg()
    generate_m3u(INPUT_FILE, OUTPUT_FILE)