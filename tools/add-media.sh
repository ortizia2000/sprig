#!/bin/bash
# add-media.sh — mete imagenes y videos a docs/media/ listos para publicar,
# los sube a GitHub Pages y devuelve las URLs publicas.
#
#   ./tools/add-media.sh <prefijo> <archivo> [archivo...]
#
# Imagenes -> JPEG. Instagram Graph API NO acepta PNG en image_url.
#             Se reescalan a max 1440px de ancho (tope de IG para feed).
# Videos   -> MP4 H.264 + AAC, faststart. Formato de Reels.
#
# Limites: GitHub 100MB por archivo, Pages ~1GB total. Un reel de 90s
# en 1080x1920 sale ~15-25MB, cabe. Video largo NO va aqui.

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
MEDIA="$REPO/docs/media"
BASE="https://ortizia2000.github.io/sprig/media"
mkdir -p "$MEDIA"

[ $# -lt 2 ] && { echo "uso: $0 <prefijo> <archivo> [archivo...]"; exit 1; }
PREFIX="$1"; shift

i=0; URLS=()
for src in "$@"; do
  [ -f "$src" ] || { echo "salto (no existe): $src"; continue; }
  i=$((i+1))
  ext="${src##*.}"; lower=$(echo "$ext" | tr 'A-Z' 'a-z')
  case "$lower" in
    png|jpg|jpeg|heic|webp)
      out="$MEDIA/${PREFIX}-${i}.jpg"
      sips -s format jpeg -s formatOptions 90 --resampleWidth 1440 "$src" --out "$out" >/dev/null 2>&1
      ;;
    mp4|mov|m4v|webm)
      out="$MEDIA/${PREFIX}-${i}.mp4"
      ffmpeg -y -loglevel error -i "$src" \
        -c:v libx264 -profile:v high -pix_fmt yuv420p -crf 23 -preset medium \
        -c:a aac -b:a 128k -movflags +faststart "$out"
      dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out" 2>/dev/null | cut -d. -f1)
      [ -n "${dur:-}" ] && [ "$dur" -gt 90 ] && echo "  AVISO: ${dur}s, Reels corta en 90s"
      ;;
    *) echo "salto (formato no soportado): $src"; continue ;;
  esac
  sz=$(du -h "$out" | cut -f1 | tr -d ' ')
  echo "  $(basename "$out")  $sz"
  URLS+=("$BASE/$(basename "$out")")
done

[ ${#URLS[@]} -eq 0 ] && { echo "nada que subir"; exit 1; }

cd "$REPO"
git add docs/media
git commit -q -m "media: add $PREFIX (${#URLS[@]} archivos)" || { echo "sin cambios que commitear"; }
git push -q origin main
echo
echo "URLs publicas (Pages tarda ~1 min en servirlas):"
printf '%s\n' "${URLS[@]}"
