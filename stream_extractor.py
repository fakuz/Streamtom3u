#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import requests
import gzip
import difflib
import xml.etree.ElementTree as ET

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

epg_channels = {}  # tvg-id -> name


def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado.")
        return False


def normalize_name(name):
    """Normaliza nombre para comparación"""
    name = re.sub(r"\b(en vivo|live)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\d{4}-\d{2}-\d{2}", "", name)  # quitar fechas
    name = re.sub(r"[-|]", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def load_epg():
    print("[INFO] Cargando EPG...")
    for url in EPG_URLS:
        try:
            print(f"[INFO] Descargando EPG: {url}")
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, timeout=20, headers=headers)
            resp.raise_for_status()

            if url.endswith(".gz"):
                xml_data = gzip.decompress(resp.content).decode("utf-8", errors="ignore")
            else:
                xml_data = resp.text

            root = ET.fromstring(xml_data)
            count = 0
            for channel in root.findall("channel"):
                tvg_id = channel.get("id")
                display_name = channel.find("display-name")
                if tvg_id and display_name is not None:
                    epg_channels[tvg_id.lower()] = display_name.text.strip()
                    count += 1

            print(f"[INFO] EPG procesado: {url} ({count} canales)")

        except Exception as e:
            print(f"[WARNING] No se pudo descargar/parsing el EPG {url}: {e}")


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
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category


def match_epg_name(original_name):
    """Encuentra el nombre más similar en EPG, si existe"""
    norm_name = normalize_name(original_name)
    epg_names = list(epg_channels.values())
    best_match = difflib.get_close_matches(norm_name, [normalize_name(n) for n in epg_names], n=1, cutoff=0.6)
    if best_match:
        idx = [normalize_name(n) for n in epg_names].index(best_match[0])
        return epg_names[idx]
    return original_name


def get_stream_info(stream_url):
    try:
        auth_opts = get_auth_options(stream_url)

        # URL de stream
        cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"] + auth_opts + [stream_url]
        url = run_command(cmd)
        if not url:
            return None, None, None, None

        # Título original
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"

        # Renombrar si EPG tiene nombre oficial
        title = match_epg_name(title)

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

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        success, fail = 0, 0
        for line in lines:
            url, category = parse_line(line)
            m3u8_url, title, thumbnail, tvg_id = get_stream_info(url)
            if m3u8_url:
                if thumbnail:
                    out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{title}\n{m3u8_url}\n')
                else:
                    out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{m3u8_url}\n')
                success += 1
            else:
                fail += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success} streams agregados correctamente.")
    if fail > 0:
        print(f"⚠ {fail} enlaces fallaron.")


if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    load_epg()
    generate_m3u(INPUT_FILE, OUTPUT_FILE)