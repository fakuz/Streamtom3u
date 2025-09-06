#!/usr/bin/env python3
import subprocess
import os
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Calidad y compatibilidad
MAX_RESOLUTION = 1080        # Resolución máxima (ej. 720, 1080)
FORCE_HLS = True             # True = Forzar streams HLS cuando sea posible
CODEC_FILTER = "[vcodec*=avc1]"  # Forzar H.264 (mejor compatibilidad)

# Fallback: archivo M3U8 fijo cuando el canal falla
FALLBACK_STREAM = "https://raw.githubusercontent.com/fakuz/Streamtom3u/refs/heads/main/fallback/fallback.m3u8"

# Lista de EPGs
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml"
]

# Número máximo de hilos
MAX_THREADS = 10
# =======================================================

def build_format_selector():
    return f"bv*[height<={MAX_RESOLUTION}]{CODEC_FILTER}+bestaudio/best"

FORMAT_SELECTOR = build_format_selector()

def check_yt_dlp():
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado.")
        return False

def cookies_available():
    return os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def normalize_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())

def parse_line(line):
    """Devuelve (url, categoria, canal) desde la línea del archivo."""
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    channel = parts[2].strip() if len(parts) > 2 else None
    return url, category, channel

def get_stream_info(line):
    url, category, channel_name = parse_line(line)
    try:
        # Construir comando para URL M3U8
        cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"]
        if FORCE_HLS:
            cmd.append("--hls-use-mpegts")
        if cookies_available():
            cmd += ["--cookies", "cookies.txt"]
        cmd.append(url)

        m3u8_url = run_command(cmd)

        # Título: usar canal si está, sino el título original
        title = channel_name or run_command(["yt-dlp", "--get-title"] + (["--cookies", "cookies.txt"] if cookies_available() else []) + [url]) or "Stream"

        # Thumbnail
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + (["--cookies", "cookies.txt"] if cookies_available() else []) + [url])

        # ID único
        if "youtu" in url:
            match = re.search(r"(?:v=|youtu\\.be/)([a-zA-Z0-9_-]{6,})", url)
            tvg_id = match.group(1).lower() if match else normalize_id(title)
        else:
            tvg_id = normalize_id(title)

        # Si falla, usar fallback fijo
        if not m3u8_url:
            print(f"[WARNING] No se pudo obtener M3U8 de: {url}. Usando fallback.")
            title_display = f"{title} (OFF AIR)"
            if thumbnail:
                return f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{title_display}\n{FALLBACK_STREAM}\n'
            else:
                return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title_display}\n{FALLBACK_STREAM}\n'

        # Si funciona, usar stream real
        if thumbnail:
            return f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{title}\n{m3u8_url}\n'
        else:
            return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{m3u8_url}\n'

    except Exception:
        # Si hay error inesperado, también fallback
        title_display = (channel_name or "Stream") + " (OFF AIR)"
        return f'#EXTINF:-1 group-title="{category}",{title_display}\n{FALLBACK_STREAM}\n'

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
    success_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_line = {executor.submit(get_stream_info, line): line for line in lines}
            for future in as_completed(future_to_line):
                result = future.result()
                if result:
                    out.write(result)
                    success_count += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success_count} streams agregados (con fallback si falló).")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    print(f"[CONFIG] Resolución máxima: {MAX_RESOLUTION}px | Códec: H.264 | HLS forzado: {FORCE_HLS}")
    print(f"[CONFIG] Fallback: {FALLBACK_STREAM}")
    print(f"[CONFIG] Cookies: {'Sí (cookies.txt encontrado)' if cookies_available() else 'No'}")
    generate_m3u(INPUT_FILE, OUTPUT_FILE)