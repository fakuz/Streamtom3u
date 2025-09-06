#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import random
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIG ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Fallback fijo de tu repo (VOD HLS que siempre está online)
FALLBACK_URL = "https://raw.githubusercontent.com/fakuz/Streamtom3u/refs/heads/main/fallback/fallback.m3u8"

# EPG opcional
EPG_URLS = ["https://iptv-org.github.io/epg/guides/es.xml"]

# Concurrencia
MAX_THREADS = 10

# Timeouts por request (rápidos para GitHub Actions)
HTTP_TIMEOUT = 4

# Reintentos por API (ligeros)
API_RETRIES = 2

# Instancias Piped (muchas, para rotar y evitar bloqueos)
PIPED_APIS = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.jae.fi",
    "https://pipedapi.r4fo.com",
    "https://pipedapi.syncpundit.io",
    "https://pipedapi.in.projectsegfau.lt",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.privacy.com.de",
    "https://pipedapi.us.projectsegfau.lt",
    "https://pipedapi.qdi.fi",
    "https://pipedapi.drgns.space",
    "https://pipedapi.smnz.de",
]

# Instancias Invidious (segunda capa)
INVIDIOUS_APIS = [
    "https://yewtu.be",
    "https://invidious.projectsegfau.lt",
    "https://inv.n8pjl.ca",
    "https://invidious.nerdvpn.de",
    "https://invidious.lunar.icu",
    "https://inv.tux.pizza",
    "https://invidious.lidarshield.cloud",
    "https://invidious.private.coffee",
    "https://ytb.dedyn.io",
    "https://iv.ggtyler.dev",
]

# Persistencia simple en memoria de la última instancia que funcionó
_last_piped_ok = None
_last_invidious_ok = None
# =================================================


# -------------------- Utilidades --------------------
def normalize_id(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


def parse_line(line: str):
    """Parsea 'URL | Categoria | Nombre' con defaults razonables."""
    parts = [p.strip() for p in line.split("|")]
    url = parts[0]
    category = parts[1] if len(parts) > 1 and parts[1] else "General"
    channel_name = parts[2] if len(parts) > 2 and parts[2] else url
    return url, category, channel_name


def extract_youtube_id(url: str):
    # v=XXXXXXXX o youtu.be/XXXXXXXX
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    return m.group(1) if m else None


def http_get_json(url: str, timeout=HTTP_TIMEOUT):
    headers = {
        "User-Agent": f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      f"(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


# -------------------- Extracción por APIs --------------------
def get_stream_from_piped(video_id: str) -> str | None:
    """Intenta HLS o DASH desde Piped (varias instancias, rotación rápida)."""
    global _last_piped_ok

    candidates = PIPED_APIS[:]
    random.shuffle(candidates)
    if _last_piped_ok and _last_piped_ok in candidates:
        # prueba primero la última que funcionó
        candidates.remove(_last_piped_ok)
        candidates.insert(0, _last_piped_ok)

    for api in candidates:
        url = f"{api}/streams/{video_id}"
        for _ in range(API_RETRIES):
            try:
                data = http_get_json(url)
                # Piped suele retornar keys 'hls' y/o 'dash'
                hls = data.get("hls")
                dash = data.get("dash")
                if hls:  # Prioriza HLS
                    _last_piped_ok = api
                    return hls
                if dash:
                    _last_piped_ok = api
                    return dash
            except Exception:
                # siguiente intento/instancia
                continue
    return None


def get_stream_from_invidious(video_id: str) -> str | None:
    """Intenta obtener HLS/DASH desde Invidious (varias instancias)."""
    global _last_invidious_ok

    candidates = INVIDIOUS_APIS[:]
    random.shuffle(candidates)
    if _last_invidious_ok and _last_invidious_ok in candidates:
        candidates.remove(_last_invidious_ok)
        candidates.insert(0, _last_invidious_ok)

    for api in candidates:
        url = f"{api}/api/v1/videos/{video_id}"
        for _ in range(API_RETRIES):
            try:
                data = http_get_json(url)
                # Invidious puede tener: hlsUrl, dashUrl, adaptiveFormats
                hls = data.get("hlsUrl")
                dash = data.get("dashUrl")
                if hls:
                    _last_invidious_ok = api
                    return hls
                if dash:
                    _last_invidious_ok = api
                    return dash

                # Examinar adaptiveFormats (por si expone HLS)
                adaptive = data.get("adaptiveFormats") or []
                for fmt in adaptive:
                    # Algunos devuelven 'type': 'application/x-mpegURL'
                    mime = fmt.get("type", "")
                    url_fmt = fmt.get("url")
                    if "application/x-mpegurl" in mime.lower() and url_fmt:
                        _last_invidious_ok = api
                        return url_fmt
            except Exception:
                continue
    return None


# -------------------- yt-dlp (sin cookies) --------------------
def get_stream_with_ytdlp(url: str) -> str | None:
    """Prueba con yt-dlp sin cookies (rápido)."""
    try:
        cmd = ["yt-dlp", "-f", "b", "-g", "--no-check-certificate", url]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip().splitlines()[-1]
    except Exception:
        pass
    return None


def check_yt_dlp_installed() -> bool:
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception:
        return False


# -------------------- Flujo por URL --------------------
def resolve_stream(line: str) -> str:
    """Devuelve línea EXTINF + URL (o fallback) para una entrada de links.txt."""
    url, category, channel_name = parse_line(line)
    tvg_id = normalize_id(channel_name)
    stream_url = None

    # 1) Si es YouTube: Piped → Invidious
    if "youtube.com" in url or "youtu.be" in url:
        vid = extract_youtube_id(url)
        if vid:
            stream_url = get_stream_from_piped(vid)
            if not stream_url:
                stream_url = get_stream_from_invidious(vid)

    # 2) Si no hay aún: probar yt-dlp sin cookies (sirve para varios sitios)
    if not stream_url and check_yt_dlp_installed():
        stream_url = get_stream_with_ytdlp(url)

    # 3) Si todo falla: fallback fijo
    if not stream_url:
        print(f"[WARNING] No se pudo obtener stream de: {url}. Usando fallback.")
        stream_url = FALLBACK_URL

    return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{channel_name}\n{stream_url}\n'


# -------------------- Generación M3U --------------------
def generate_m3u(input_path: str, output_path: str):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    # Cabecera M3U
    epg_line = ",".join(EPG_URLS)
    if os.path.exists(output_path):
        print(f"[INFO] El archivo {output_path} ya existe. Será sobrescrito.")

    print(f"[CONFIG] Fallback: {FALLBACK_URL}")
    print(f"[CONFIG] Piped: {len(PIPED_APIS)} instancias | Invidious: {len(INVIDIOUS_APIS)} instancias")

    success_count = 0
    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as ex:
            futures = {ex.submit(resolve_stream, line): line for line in lines}
            for fut in as_completed(futures):
                extinf = fut.result()
                if extinf:
                    out.write(extinf)
                    success_count += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success_count} streams procesados (Piped → Invidious → yt-dlp → fallback).")


# -------------------- Main --------------------
if __name__ == "__main__":
    # requests es obligatorio; yt-dlp es opcional (mejora tasa de aciertos)
    try:
        import requests as _
    except Exception:
        print("[ERROR] Falta 'requests'. Instálalo con: pip install -r requirements.txt")
        sys.exit(1)

    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] No se encontró {INPUT_FILE}")
        sys.exit(1)

    generate_m3u(INPUT_FILE, OUTPUT_FILE)