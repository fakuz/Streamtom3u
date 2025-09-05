#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import json
import gzip
import urllib.request
import xml.etree.ElementTree as ET
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"
MAX_WORKERS = 8

# Forzar resolución máxima a 1080p
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"

# EPGs a usar
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]

# Nivel mínimo de similitud para considerar un match (0 a 1)
FUZZY_CUTOFF = 0.8
# =======================================================

EPG_CACHE = "channels.json"

# -------------------- FUNCIONES --------------------

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

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category

def download_epg_data():
    if os.path.exists(EPG_CACHE):
        with open(EPG_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)

    channels = {}
    for epg_url in EPG_URLS:
        try:
            if epg_url.endswith(".gz"):
                with urllib.request.urlopen(epg_url) as response:
                    data = gzip.decompress(response.read())
            else:
                with urllib.request.urlopen(epg_url) as response:
                    data = response.read()

            root = ET.fromstring(data)
            for channel in root.findall("channel"):
                cid = channel.attrib.get("id")
                name = channel.findtext("display-name")
                logo = ""
                icon = channel.find("icon")
                if icon is not None and "src" in icon.attrib:
                    logo = icon.attrib["src"]
                if cid and name:
                    channels[name.lower()] = {"id": cid, "name": name, "logo": logo}
        except Exception:
            pass

    with open(EPG_CACHE, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

    return channels

def find_epg_match(title, epg_channels):
    key = title.lower()
    names = list(epg_channels.keys())
    match = difflib.get_close_matches(key, names, n=1, cutoff=FUZZY_CUTOFF)
    if match:
        best = match[0]
        return epg_channels[best]["id"], epg_channels[best]["name"], epg_channels[best]["logo"]
    return None, None, None

def get_stream_info(stream_url, category, epg_channels):
    try:
        auth_opts = get_auth_options(stream_url)

        # Obtener URL de stream forzando 1080p
        url = run_command(["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"] + auth_opts + [stream_url])
        if not url:
            return None

        # Obtener título original
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"

        # Buscar match en EPG (con fuzzy matching)
        epg_id, epg_name, epg_logo = find_epg_match(title, epg_channels)

        if epg_id and epg_name:
            tvg_id = epg_id
            title = epg_name  # Forzar nombre oficial si hay match
            logo = epg_logo
        else:
            tvg_id = normalize_id(title)
            logo = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [stream_url])

        return {"url": url, "title": title, "logo": logo, "tvg_id": tvg_id, "category": category}
    except Exception:
        return None

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        return

    epg_channels = download_epg_data()
    epg_line = ",".join(EPG_URLS)

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_stream_info, *parse_line(line), epg_channels): line for line in lines}
        for future in as_completed(futures):
            data = future.result()
            if data:
                results.append(data)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        for item in results:
            logo_part = f' tvg-logo="{item["logo"]}"' if item["logo"] else ""
            out.write(f'#EXTINF:-1 tvg-id="{item["tvg_id"]}"{logo_part} group-title="{item["category"]}",{item["title"]}\n{item["url"]}\n')

# -------------------- MAIN --------------------
if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    generate_m3u(INPUT_FILE, OUTPUT_FILE)