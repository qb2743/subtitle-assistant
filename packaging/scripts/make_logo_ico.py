"""Generate logo.ico from resource/assets/logo.png for Windows exe/installer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
png = ROOT / "resource" / "assets" / "logo.png"
ico = ROOT / "resource" / "assets" / "logo.ico"
if not png.is_file():
    raise SystemExit(f"Missing {png}")

from PIL import Image

img = Image.open(png).convert("RGBA")
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img.save(ico, format="ICO", sizes=sizes)
print(f"Wrote {ico}")