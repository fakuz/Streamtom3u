import os
import re
import requests
import gzip
import xml.etree.ElementTree as ET
from rapidfuzz import process, fuzz
from unidecode import unidecode
import yt_dlp

M3U_HEADER = '#EXTM3U url-tvg="https://iptv-org.github.io/epg/guides/es.xml,https://iptv-org.github.io/epg/guides/us.xml,https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"'

EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]

OUTPUT_FILE = "streams.m3u"
INPUT_FILE = "links.txt"


def normalize_text(text):
    """Convierte texto a minúsculas sin acentos ni caracteres especiales."""
    return unidecode(text.strip().lower()) if text else ""


def download_epg(url):
    print(f"[INFO] Descargando EPG: {url}")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()

        # Si es .gz, descomprimir
        if url.endswith(".gz"):
            data = gzip.decompress(resp.content)
        else:
            data = resp.content

        return data
    except Exception as e:
        print(f"[ERROR] No se pudo descargar {url}: {e}")
        return None


def parse_epg(epg_data):
    epg_channels = {}
    try:
        root = ET.fromstring(epg_data)
        for channel in root.findall("channel"):
            tvg_id = channel.attrib.get("id", "").strip()
            name_tag = channel.find("display-name")
            name = name_tag.text.strip() if name_tag is not None else tvg_id
            if tvg_id and name:
                epg_channels[tvg_id] = name
        return epg_channels
    except Exception as e:
        print(f"[ERROR] No se pudo procesar EPG: {e}")
        return {}


def extract_stream_info(url):
    """Obtiene título, thumbnail y stream URL usando yt-dlp."""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "format": "best",
        "cookies": "cookies.txt" if os.path.exists("cookies.txt") else None
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "Sin título")
            thumbnail = info.get("thumbnail", "")
            final_url = info.get("url", url)
            return title, thumbnail, final_url
    except Exception as e:
        print(f"[ERROR] No se pudo extraer info para {url}: {e}")
        return None, None, url


def find_best_match(title, epg_channels):
    """Busca coincidencia exacta en tvg-id o fuzzy por nombre."""
    normalized_title = normalize_text(title)

    # 1. Coincidencia exacta con tvg-id (si existe)
    if title in epg_channels:
        return epg_channels[title]

    # 2. Coincidencia fuzzy por nombre
    choices = [(normalize_text(name), name) for name in epg_channels.values()]
    match = process.extractOne(normalized_title, [c[0] for c in choices], scorer=fuzz.WRatio)
    if match and match[1] > 85:  # Similaridad mínima 85%
        index = [c[0] for c in choices].index(match[0])
        return choices[index][1]

    return None


def main():
    print("[INFO] Cargando EPG...")
    epg_channels = {}
    for url in EPG_URLS:
        data = download_epg(url)
        if data:
            epg_channels.update(parse_epg(data))

    print(f"[INFO] EPG cargado: {len(epg_channels)} canales")

    print("[INFO] Generando playlist...")
    lines = [M3U_HEADER]

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] No existe {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    for url in urls:
        title, logo, stream_url = extract_stream_info(url)
        if not stream_url:
            continue

        best_match = find_best_match(title, epg_channels)
        final_name = best_match if best_match else title

        lines.append(f'#EXTINF:-1 tvg-id="" tvg-logo="{logo}" group-title="General",{final_name}')
        lines.append(stream_url)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✅ Archivo M3U generado: {OUTPUT_FILE}")
    print(f"✔ {len(urls)} streams agregados correctamente.")


if __name__ == "__main__":
    main()