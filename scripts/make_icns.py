"""Generate a macOS ICNS file from the existing branded ICO."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    source = ROOT / "icon_2.ico"
    if not source.exists():
        source = ROOT / "icon.ico"
    output_dir = ROOT / "build_assets"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / "icon.icns"
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-icon-") as value:
        iconset = Path(value) / "icon.iconset"
        iconset.mkdir()
        image = Image.open(source).convert("RGBA")
        for size in (16, 32, 128, 256, 512):
            image.resize((size, size), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            retina = size * 2
            image.resize((retina, retina), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        # iconutil writes the ICNS next to the iconset, then it is copied in.
        temporary = Path(value) / "icon.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(temporary)], check=True)
        shutil.copy2(temporary, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
