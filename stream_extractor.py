#!/usr/bin/env python3
import subprocess
import os
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

# Calidad máxima
FORMAT_SELECTOR = "bestvideo+bestaudio/best"

# Lista de EPGs
EPG_URLS = [
    "https://iptv-org.github.io/epg/guides/es.xml",
    "https://iptv-org.github.io/epg/guides/us.xml"
]

# Número máximo de hilos (ajusta según CPU)
MAX_THREADS = 10
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

def get_stream_info(line):
    url, category = parse_line(line)
    try:
        auth_opts = get_auth_options(url)

        # URL del stream en mejor calidad
        m3u8_url = run_command(["yt-dlp", "-f", FORMAT_SELECTOR, "-g", "--no-check-certificate"] + auth_opts + [url])
        if not m3u8_url:
            return None

        # Título y logo
        title = run_command(["yt-dlp", "--get-title"] + auth_opts + [url]) or "Stream"
        thumbnail = run_command(["yt-dlp", "--get-thumbnail"] + auth_opts + [url])

        # ID único
        if "youtu" in url:
            match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", url)
            tvg_id = match.group(1).lower() if match else normalize_id(title)
        else:
            tvg_id = normalize_id(title)

        # Construir línea M3U
        if thumbnail:
            m3u_line = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{thumbnail}" group-title="{category}",{title}\n{m3u8_url}\n'
        else:
            m3u_line = f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{m3u8_url}\n'

        return m3u_line

    except Exception:
        return None

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
    fail_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write(f'#EXTM3U url-tvg="{epg_line}"\n')

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_line = {executor.submit(get_stream_info, line): line for line in lines}
            for future in as_completed(future_to_line):
                result = future.result()
                if result:
                    out.write(result)
                    success_count += 1
                else:
                    fail_count += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success_count} streams agregados correctamente.")
    if fail_count > 0:
        print(f"⚠ {fail_count} enlaces fallaron.")

if __name__ == "__main__":
    if not check_yt_dlp():
        sys.exit(1)

    if os.path.exists(OUTPUT_FILE):
        print(f"[INFO] El archivo {OUTPUT_FILE} ya existe. Será sobrescrito.")

    generate_m3u(INPUT_FILE, OUTPUT_FILE)