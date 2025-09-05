#!/usr/bin/env python3
import subprocess
import os
import sys
import re

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Selección de calidad:
# - Máxima calidad: "bestvideo+bestaudio/best"
# - Límite 1080p: "bestvideo[height<=1080]+bestaudio/best"
# - Preferir AV1: "bestvideo[codec^=av01]+bestaudio/best"
FORMAT_SELECTOR = "bestvideo+bestaudio/best"

# Lista de EPGs (puedes agregar varias separadas por coma)
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml"
]
# =======================================================

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
        print("[INFO] Usando cookies.txt para autenticación.")
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

def get_stream_info(stream_url):
    try:
        auth_opts = get_auth_options(stream_url)

        # Construir comando para obtener la mejor calidad disponible
        cmd = [
            "yt-dlp",
            "-f", FORMAT_SELECTOR,
            "-g", "--no-check-certificate"
        ] + auth_opts + [stream_url]

        # URL del stream
        url = run_command(cmd)
        if not url:
            print(f"[ERROR] No se pudo obtener URL para: {stream_url}")
            return None, None, None, None

        # Título
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [stream_url]) or "Stream"

        # Thumbnail
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [stream_url])

        # ID único (para EPG)
        if "youtu" in stream_url:
            match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", stream_url)
            tvg_id = match.group(1).lower() if match else normalize_id(title)
        else:
            tvg_id = normalize_id(title)

        return url, title, thumbnail, tvg_id

    except Exception as e:
        print(f"[EXCEPTION] Error procesando {stream_url}: {e}")
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

    success, fail = 0, 0

    epg_line = ",".join(EPG_URLS)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')
        for line in lines:
            url, category = parse_line(line)
            print(f"[INFO] Procesando: {url} (Categoría: {category})")
            m3u8_url, title, thumbnail, tvg_id = get_stream_info(url)
            if m3u8_url:
                if thumbnail:
                    out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{title}\n{m3u8_url}\n')
                else:
                    out.write(f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{m3u8_url}\n')
                success += 1
            else:
                print(f"[WARNING] No se pudo obtener M3U8 de: {url}")
                fail += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success} streams agregados correctamente.")
    if fail > 0:
        print(f"⚠ {fail} enlaces fallaron.")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    generate_m3u(INPUT_FILE, OUTPUT_FILE)