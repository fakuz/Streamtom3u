import subprocess
import os

INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

def get_m3u8_url(stream_url):
    try:
        result = subprocess.run(
            ["yt-dlp", "-f", "best", "-g", stream_url],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] No se pudo procesar: {stream_url}")
        return None

def generate_m3u(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r") as f:
        links = [line.strip() for line in f if line.strip()]

    with open(output_path, "w") as out:
        out.write("#EXTM3U\n")
        for link in links:
            print(f"[INFO] Procesando: {link}")
            m3u8_url = get_m3u8_url(link)
            if m3u8_url:
                out.write("#EXTINF:-1," + link + "\n")
                out.write(m3u8_url + "\n")

    print(f"\n✅ Archivo M3U generado: {output_path}")

if __name__ == "__main__":
    generate_m3u(INPUT_FILE, OUTPUT_FILE)