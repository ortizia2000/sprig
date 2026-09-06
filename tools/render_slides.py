#!/usr/bin/env python3
"""Render HTML slides to the JPEGs Instagram fetches.

    python tools/render_slides.py                # every stale set under slides/
    python tools/render_slides.py banquete-mta   # one set
    python tools/render_slides.py --check        # report STALE/FRESH, render nothing
    python tools/render_slides.py --force        # ignore the manifest
    python tools/render_slides.py --record <set> # pin the manifest to the current
                                                 # sources WITHOUT rendering (the
                                                 # JPEGs on disk are the approved ones)

Layout:  slides/<post-id>/s1.html … sN.html + tpl.css + any images
Output:  docs/media/<post-id>-<n>.jpg AND content/media/<post-id>-<n>.jpg
         (both places the publisher/dashboard already read from), 1440x1800
         JPEG q90 — same size/format tools/add-media.sh produces.

Each set carries a manifest.json with a sha256 over its sources. A set whose
hash matches is skipped, so the GitHub Action never re-renders an unchanged
set on a machine with different fonts and silently swaps the images under a
post that is already scheduled. Edit any source file (or --force) to re-render.

Chrome: $CHROME, else the macOS app, else google-chrome / chromium on PATH.
Rendered at device scale 2 (2160x2700) and downsampled, which is how the
existing carousels were produced.
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_W, OUT_H = 1440, 1800
JPEG_QUALITY = 90
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
]
SOURCE_EXT = (".html", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".woff", ".woff2", ".ttf", ".otf")


def find_chrome():
    env = os.environ.get("CHROME")
    if env:
        return env if os.path.isfile(env) and os.access(env, os.X_OK) else None
    for c in CHROME_CANDIDATES:
        if os.path.isabs(c):
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        elif shutil.which(c):
            return shutil.which(c)
    return None


def slides_root():
    return os.path.join(ROOT, "slides")


def slide_files(set_dir):
    """s1.html … sN.html in numeric order."""
    names = [f for f in os.listdir(set_dir) if re.fullmatch(r"s(\d+)\.html", f)]
    return sorted(names, key=lambda f: int(re.fullmatch(r"s(\d+)\.html", f).group(1)))


def source_hash(set_dir):
    h = hashlib.sha256()
    for f in sorted(os.listdir(set_dir)):
        if f == "manifest.json" or not f.lower().endswith(SOURCE_EXT):
            continue
        h.update(f.encode())
        with open(os.path.join(set_dir, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def manifest_path(set_dir):
    return os.path.join(set_dir, "manifest.json")


def read_manifest(set_dir):
    try:
        with open(manifest_path(set_dir)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_manifest(set_dir, sha, outputs):
    with open(manifest_path(set_dir), "w") as f:
        json.dump({"sha256": sha, "outputs": outputs, "size": [OUT_W, OUT_H]}, f, indent=2)
        f.write("\n")


def output_dirs():
    return [os.path.join(ROOT, "docs", "media"), os.path.join(ROOT, "content", "media")]


def render_slide(chrome, html_path, png_path):
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
           "--force-device-scale-factor=2", f"--window-size=1080,1350",
           f"--screenshot={png_path}", "file://" + os.path.abspath(html_path)]
    subprocess.run(cmd, capture_output=True, timeout=120)
    return os.path.isfile(png_path) and os.path.getsize(png_path) > 0


def to_jpeg(png_path):
    from PIL import Image
    im = Image.open(png_path).convert("RGB")
    if im.size != (OUT_W, OUT_H):
        im = im.resize((OUT_W, OUT_H), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


def render_set(chrome, name, set_dir):
    """Returns the list of output basenames, or None if any slide failed."""
    files = slide_files(set_dir)
    if not files:
        print(f"SKIP {name}: no s<N>.html files", file=sys.stderr)
        return None
    outputs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(files, 1):
            png = os.path.join(tmp, f"{i}.png")
            if not render_slide(chrome, os.path.join(set_dir, f), png):
                print(f"FAIL {name} {f}: Chrome produced no screenshot", file=sys.stderr)
                return None
            data = to_jpeg(png)
            out_name = f"{name}-{i}.jpg"
            for d in output_dirs():
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, out_name), "wb") as fh:
                    fh.write(data)
            outputs.append(out_name)
            print(f"OK   {name} {f} -> {out_name} ({len(data) // 1024} KB)")
    return outputs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sets", nargs="*", help="slide set names (default: all)")
    ap.add_argument("--check", action="store_true", help="report STALE/FRESH, render nothing")
    ap.add_argument("--force", action="store_true", help="re-render even when the manifest matches")
    ap.add_argument("--record", action="store_true",
                    help="write the manifest for the current sources without rendering "
                         "(use when the JPEGs on disk are the approved renders)")
    a = ap.parse_args(argv)

    root = slides_root()
    available = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))) \
        if os.path.isdir(root) else []
    if a.sets:
        unknown = [s for s in a.sets if s not in available]
        if unknown:
            print(f"unknown slide set(s): {', '.join(unknown)} — have: {', '.join(available) or 'none'}",
                  file=sys.stderr)
            return 1
        names = a.sets
    else:
        names = available
    if not names:
        print("no slide sets under slides/")
        return 0

    chrome = None
    if not (a.check or a.record):
        chrome = find_chrome()
        if not chrome:
            print("No Chrome found. Set CHROME=/path/to/chrome (macOS: the app binary; "
                  "Linux: google-chrome or chromium).", file=sys.stderr)
            return 2

    failed = 0
    for name in names:
        set_dir = os.path.join(root, name)
        sha = source_hash(set_dir)
        fresh = read_manifest(set_dir).get("sha256") == sha
        if a.record:
            outputs = [f"{name}-{i}.jpg" for i in range(1, len(slide_files(set_dir)) + 1)]
            missing = [o for o in outputs if not all(os.path.isfile(os.path.join(d, o)) for d in output_dirs())]
            if missing:
                print(f"FAIL {name}: cannot record, outputs missing on disk: {', '.join(missing)}",
                      file=sys.stderr)
                failed += 1
                continue
            write_manifest(set_dir, sha, outputs)
            print(f"RECORDED {name} ({len(outputs)} slides, sha {sha[:12]})")
            continue
        if a.check:
            print(f"{'FRESH' if fresh else 'STALE'} {name}")
            continue
        if fresh and not a.force:
            print(f"SKIP {name}: sources unchanged since last render")
            continue
        outputs = render_set(chrome, name, set_dir)
        if outputs is None:
            failed += 1
            continue
        write_manifest(set_dir, sha, outputs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
