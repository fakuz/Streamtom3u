import os
import random
import requests
import subprocess

# ===== CONFIGURACIÓN DE PROXIES =====
# Lista de proxies (puede venir de un archivo o estar fija)
PROXY_LIST_FILE = "proxies.txt"
PROXIES = []

if os.path.exists(PROXY_LIST_FILE):
    with open(PROXY_LIST_FILE, "r", encoding="utf-8") as f:
        PROXIES = [line.strip() for line in f if line.strip()]

def get_random_proxy():
    return random.choice(PROXIES) if PROXIES else None

def get_requests_proxy():
    proxy = get_random_proxy()
    return {"http": proxy, "https": proxy} if proxy else None

# ===== FUNCIONES DE STREAM =====
def get_stream_from_piped(video_id):
    try:
        url = f"https://piped.video/streams/{video_id}"
        proxy = get_requests_proxy()
        response = requests.get(url, proxies=proxy, timeout=10)
        if response.status_code == 200:
            data = response.json()
            hls = data.get("hls")
            if hls:
                return hls
    except Exception as e:
        print(f"[ERROR] Piped fallo para {video_id}: {e}")
    return None

def get_stream_with_ytdlp(url):
    proxy = get_random_proxy()
    cmd = ["yt-dlp", "--geo-bypass", "-f", "best", "--get-url"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        print(f"[ERROR] yt-dlp fallo: {e}")
    return None