#!/usr/bin/env python3
import subprocess
import os
import sys

INPUT_FILE = "links.txt"
OUTPUT_FILE = "streams.m3u"

def check_yt_dlp():
    """Verifica si yt-dlp está instalado."""
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("[ERROR] yt-dlp no está instalado o no está en el PATH.")
        return False
    except subprocess.CalledProcessError as e:
        print("[ERROR] No se pudo ejecutar yt-dlp:", e.stderr)
        return False

def get_stream_info(stream_url):
    """Obtiene URL M3U8 y título del stream, con soporte para cookies."""
    try:
        yt_dlp_cmd = [
            "yt-dlp",
            "-f", "b",  # Mejor opción para streams
            "-g",
            "--no-check-certificate"
        ]

        # Si hay cookies.txt, lo usamos
        if os.path.exists("cookies.txt"):
            yt_dlp_cmd += ["--cookies", "cookies.txt"]

        yt_dlp_cmd.append(stream_url)

        print(f"[DEBUG] Ejecutando: {' '.join(yt_dlp_cmd)}")
        result = subprocess.run(yt_dlp_cmd, capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            print(f"[ERROR] yt-dlp no devolvió URL para: {stream_url}")
            print(f"[yt-dlp stderr]: {result.stderr.strip()}")
            return None, None

        url = result.stdout.strip()
        print(f"[INFO] URL obtenida: {url}")

        # Obtener título del stream
        title_cmd = ["yt-dlp", "--get-title"]
        if os.path.exists("cookies.txt"):
            title_cmd += ["--cookies", "cookies.txt"]
        title_cmd.append(stream_url)

        title_result = subprocess.run(title_cmd, capture_output=True, text=True)
        title = title_result.stdout.strip() if title_result.returncode == 0 else "Desconocido"
        print(f"[INFO] Título obtenido: {title}")

        return url, title

    except Exception as e:
        print(f"[EXCEPTION] Error procesando {stream_url}: {e}")
        return None, None

def generate_m3u(input_path, output_path):
    """Genera el archivo M3U a partir de los enlaces."""
    if not os.path.exists(input_path):
        print(f"[ERROR] No se encontró el archivo: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip()]

    if not links:
        print("[ERROR] El archivo links.txt está vacío.")
        return

    success = 0
    fail = 0

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("#EXTM3U\n")
        for link in links:
            print(f"[INFO] Procesando: {link}")
            m3u8_url, title = get_stream_info(link)
            if m3u8_url:
                out.write(f"#EXTINF:-1,{title}\n{m3u8_url}\n")
                success += 1
            else:
                print(f"[WARNING] No se pudo obtener M3U8 de: {link}")
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
