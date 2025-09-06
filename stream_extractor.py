#!/usr/bin/env python3
import os
import random
import requests
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== CONFIGURACIÓN ====================
INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"
FALLBACK_URL = "https://raw.githubusercontent.com/fakuz/Streamtom3u/refs/heads/main/fallback/fallback.m3u8"

# Formato preferido y ajustes
FORMAT_SELECTOR = "bestvideo[height<=1080]+bestaudio/best"
MAX_THREADS = 10
MAX_PROXY_ATTEMPTS = 3  # Intentos con diferentes proxies antes del fallback

# Proxies
PROXY_LIST_FILE = "proxies.txt"
PROXIES = []

if os.path.exists(PROXY_LIST_FILE):
    with open(PROXY_LIST_FILE, "r", encoding="utf-8") as f:
        PROXIES = [line.strip() for line in f if line.strip()]

# =======================================================

def get_random_proxy():
    return random.choice(PROXIES) if PROXIES else None

def get_requests_proxy(proxy):
    return {"http": proxy, "https": proxy} if proxy else None

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def parse_line(line):
    """Devuelve (url, categoría, nombre)"""
    parts = line.split("|")
    url = parts[0].strip()
    category = parts[1].strip() if len(parts) > 1 else "General"
    name = parts[2].strip() if len(parts) > 2 else None
    return url, category, name

def get_stream_from_piped(video_id, proxy):
    try:
        url = f"https://piped.video/streams/{video_id}"
        response = requests.get(url, proxies=get_requests_proxy(proxy), timeout=10)
        if response.status_code == 200:
            data = response.json()
            hls = data.get("hls")
            if hls:
                return hls
    except:
        pass
    return None

def get_stream_with_ytdlp(url, proxy):
    cmd = ["yt-dlp", "-f", FORMAT_SELECTOR, "--get-url"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    return run_command(cmd)

def extract_video_id(url):
    import re
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{6,})", url)
    return match.group(1) if match else None

def get_stream_info(line):
    url, category, custom_name = parse_line(line)
    title = custom_name if custom_name else "Stream"
    tvg_logo = ""
    tvg_id = title.replace(" ", "").lower()

    # Intentos con proxies
    for attempt in range(MAX_PROXY_ATTEMPTS):
        proxy = get_random_proxy()
        if proxy:
            print(f"[INFO] Intento {attempt+1}/{MAX_PROXY_ATTEMPTS} para {title} usando proxy: {proxy}")
        else:
            print(f"[INFO] Intento {attempt+1}/{MAX_PROXY_ATTEMPTS} para {title} sin proxy")

        # 1. Intentar Piped (solo para YouTube)
        if "youtube.com" in url or "youtu.be" in url:
            video_id = extract_video_id(url)
            if video_id:
                stream_url = get_stream_from_piped(video_id, proxy)
                if stream_url:
                    return build_m3u_line(title, tvg_id, tvg_logo, category, stream_url)

        # 2. Intentar yt-dlp
        stream_url = get_stream_with_ytdlp(url, proxy)
        if stream_url:
            return build_m3u_line(title, tvg_id, tvg_logo, category, stream_url)

    # Si fallan todos los intentos → fallback
    print(f"[WARNING] No se pudo obtener stream de: {url}. Usando fallback.")
    return build_m3u_line(title, tvg_id, tvg_logo, category, FALLBACK_URL)

def build_m3u_line(title, tvg_id, tvg_logo, category, stream_url):
    if tvg_logo:
        return f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" group-title="{category}",{title}\n{stream_url}\n'
    else:
        return f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{category}",{title}\n{stream_url}\n'

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    success_count = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write('#EXTM3U\n')
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_line = {executor.submit(get_stream_info, line): line for line in lines}
            for future in as_completed(future_to_line):
                result = future.result()
                if result:
                    out.write(result)
                    success_count += 1

    print(f"\n✅ Archivo M3U generado: {output_path}")
    print(f"✔ {success_count} streams procesados (con proxies y fallback si falló).")

if __name__ == "__main__":
    generate_m3u(INPUT_FILE, OUTPUT_FILE)