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
CODEC = "h264"               # Opciones: "h264", "av1", "auto"
FORCE_HLS = True             # True = Forzar streams HLS cuando sea posible

# Fallback: video de YouTube cuando el canal falla
FALLBACK_SOURCE = "https://www.youtube.com/watch?v=E-lbpHIkaTo"
FALLBACK_STREAM = None

# Lista de EPGs
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml"
]

# Número máximo de hilos
MAX_THREADS = 10
# =======================================================

def build_format_selector():
    """Genera el formato según códec, resolución y preferencia HLS."""
    if CODEC == "h264":
        video_filter = f"bv*[height<={MAX_RESOLUTION}][vcodec*=avc1]"
    elif CODEC == "av1":
        video_filter = f"bv*[height<={MAX_RESOLUTION}][vcodec*=av01]"
    else:  # auto
        video_filter = f"bestvideo[height<={MAX_RESOLUTION}]"
    
    selector = f"{video_filter}+bestaudio/best"
    return selector

FORMAT_SELECTOR = build_format_selector()

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
    """Devuelve (url, categoria, canal) desde la línea del archivo."""
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    channel = parts[2].strip() if len(parts) > 2 else None
    return url, category, channel

def get_fallback_stream():
    print(f"[INFO] Generando URL de fallback desde {FALLBACK_SOURCE}...")
    cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"]
    if FORCE_HLS:
        cmd.append("--hls-use-mpegts")
    cmd.append(FALLBACK_SOURCE)
    return run_command(cmd)

def get_stream_info(line):
    url, category, channel_name = parse_line(line)
    try:
        auth_opts = get_auth_options(url)

        # Comando base para URL M3U8
        cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"]
        if FORCE_HLS:
            cmd.append("--hls-use-mpegts")
        cmd += auth_opts + [url]

        m3u8_url = run_command(cmd)

        # Título: usar canal si está, sino el título original
        title = channel_name or run_command(["yt-dlp", "--get-title"] + auth_opts + [url]) or "Stream"

        # Thumbnail
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [url])

        # ID único
        if "youtu" in url:
            match = re.search(r"(?:v=|youtu\\.be/)([a-zA-Z0-9_-]{6,})", url)
            tvg_id = match.group(1).lower() if match else normalize_id(title)
        else:
            tvg_id = normalize_id(title)

        # Si falla, usar fallback dinámico
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
    global FALLBACK_STREAM
    FALLBACK_STREAM = get_fallback_stream()
    if not FALLBACK_STREAM:
        print("[ERROR] No se pudo generar el fallback. Abortando.")
        sys.exit(1)

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
    print(f"✔ {success_count} streams agregados (con fallback dinámico si falló).")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    print(f"[CONFIG] Resolución máxima: {MAX_RESOLUTION}px | Códec preferido: {CODEC} | HLS forzado: {FORCE_HLS}")
    generate_m3u(INPUT_FILE, OUTPUT_FILE)