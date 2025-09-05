#!/usr/bin/env python3
import subprocess
import os
import sys
import re
import gzip
import xml.etree.ElementTree as ET
import difflib
from concurrent.futures import ThreadPoolExecutor

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"  # Forzar 1080p
THREADS = 8  # Número de hilos para procesamiento paralelo
FUZZY_CUTOFF = 0.8  # Nivel de coincidencia para EPG

EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_AR1.xml.gz"
]
# ========================================================

# Palabras irrelevantes para normalización de nombres
STOPWORDS = [
    # Generales
    "en vivo", "live", "hd", "1080p", "720p", "4k", "oficial", "canal", "latino", "24/7", "tv",
    # Deportes
    "deportes", "sport", "partido", "match", "game", "en directo", "liga", "champions", "nba", "nfl", "mlb",
    # Películas
    "películas", "movies", "cine", "film", "estreno", "movie",
    # Series
    "series", "temporada", "episodio", "capítulo", "telenovela",
    # Noticias
    "noticias", "news", "actualidad", "breaking news", "última hora",
    # Música
    "música", "music", "concierto", "live music", "videoclip", "festival", "radio", "hit", "top",
    # Infantil
    "niños", "kids", "cartoon", "dibujos", "infantil", "animación",
    # Documentales
    "documental", "docu", "historia", "nature", "science", "wild",
    # Religión
    "misa", "iglesia", "gospel", "oración", "prayer", "mass"
]

# ==================== FUNCIONES ====================

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

def normalize_title_for_match(title):
    t = title.lower()
    for w in STOPWORDS:
        t = t.replace(w, "")
    t = re.sub(r'[^a-z0-9 ]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    return url, category

def load_epg(epg_urls):
    epg_channels = {}
    for url in epg_urls:
        try:
            if url.endswith(".gz"):
                data = run_command(["curl", "-s", url])
                if data:
                    data = gzip.decompress(data.encode("latin1")).decode("utf-8")
                    root = ET.fromstring(data)
                else:
                    continue
            else:
                data = run_command(["curl", "-s", url])
                if data:
                    root = ET.fromstring(data)
                else:
                    continue

            for ch in root.findall("channel"):
                ch_id = ch.get("id")
                name = ch.findtext("display-name", "").strip()
                logo = ch.find("icon").get("src") if ch.find("icon") is not None else ""
                if name:
                    epg_channels[name.lower()] = {"id": ch_id, "name": name, "logo": logo}
        except:
            continue
    return epg_channels

def find_epg_match(title, epg_channels):
    key = normalize_title_for_match(title)
    names = [normalize_title_for_match(n) for n in epg_channels.keys()]
    normalized_map = dict(zip(names, epg_channels.keys()))
    match = difflib.get_close_matches(key, names, n=1, cutoff=FUZZY_CUTOFF)
    if match:
        best_original = normalized_map[match[0]]
        return epg_channels[best_original]["id"], epg_channels[best_original]["name"], epg_channels[best_original]["logo"]
    return None, None, None

def get_stream_info(stream_url, category, epg_channels):
    try:
        auth_opts = get_auth_options(stream_url)
        cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"] + auth_opts + [stream_url]
        url = run_command(cmd)
        if not url:
            return None

        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"
        tvg_id, epg_name, logo = find_epg_match(title, epg_channels)

        if epg_name:
            title = epg_name
        else:
            tvg_id = normalize_id(title)
            logo = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [stream_url])

        return {
            "url": url,
            "title": title,
            "category": category,
            "tvg_id": tvg_id,
            "logo": logo or ""
        }
    except:
        return None

def generate_m3u(input_path, output_path, epg_channels):
    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    epg_line = ",".join(EPG_URLS)
    results = []

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(get_stream_info, *parse_line(line), epg_channels) for line in lines]
        for future in futures:
            res = future.result()
            if res:
                results.append(res)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        for r in results:
            out.write(f'#EXTINF:-1 tvg-id="{r["tvg_id"]}" tvg-logo="{r["logo"]}" group-title="{r["category"]}",{r["title"]}\n{r["url"]}\n')

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {len(results)} streams agregados correctamente.")

# ==================== EJECUCIÓN ====================
if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    print("[INFO] Cargando EPG...")
    epg_channels = load_epg(EPG_URLS)

    print("[INFO] Generando playlist...")
    generate_m3u(INPUT_FILE, OUTPUT_FILE, epg_channels)