"""Build script for WinOptiAI-Portable.exe, WinOptiAI-Setup.exe, and SHA256SUMS.txt."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def generate_app_icon() -> Path:
    """Generate multi-resolution geometric 0px Windows .ico matching brand.svg."""
    ico_path = ASSETS / "icons" / "winoptiai.ico"
    sizes = [256, 128, 64, 48, 32, 16]
    images: list[Image.Image] = []

    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (11, 13, 16, 255))
        draw = ImageDraw.Draw(img)
        pad = max(2, sz // 8)
        stroke = max(1, sz // 16)
        # Outer sharp frame
        draw.rectangle([pad, pad, sz - pad - 1, sz - pad - 1], outline=(226, 231, 237, 255), width=stroke)
        # Architectural grid lines matching brand.svg
        split_y = int(sz * 0.42)
        split_x = int(sz * 0.42)
        draw.line([(pad, split_y), (sz - pad - 1, split_y)], fill=(226, 231, 237, 255), width=stroke)
        draw.line([(split_x, split_y), (split_x, sz - pad - 1)], fill=(226, 231, 237, 255), width=stroke)
        # Inner module block
        inner_pad = max(1, sz // 10)
        draw.rectangle(
            [
                split_x + inner_pad,
                split_y + inner_pad,
                sz - pad - inner_pad - 1,
                sz - pad - inner_pad - 1,
            ],
            fill=(203, 213, 225, 255),
        )
        images.append(img)

    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    return ico_path


def run_pyinstaller(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", *args]
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {res.returncode}")


def write_sha256_manifest(files: list[Path]) -> None:
    lines: list[str] = []
    for f in files:
        if f.exists():
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"{digest}  {f.name}")
    (DIST / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    ico_path = generate_app_icon()

    qt_excludes = [
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebEngineQuick",
        "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.QtPdfWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.Qt3DRender",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtMultimedia",
    ]

    # 1. Build standalone WinOptiAI-Portable.exe
    entry_script = ROOT / "scripts" / "pyinstaller_entry.py"
    entry_script.write_text(
        "from winoptiai.app import main\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
        encoding="utf-8",
    )

    run_pyinstaller(
        [
            "--onefile",
            "--windowed",
            "--name", "WinOptiAI-Portable",
            "--icon", str(ico_path),
            "--paths", str(ROOT / "src"),
            "--add-data", f"{ROOT / 'VERSION'};.",
            "--add-data", f"{ASSETS / 'fonts'};assets/fonts",
            "--add-data", f"{ASSETS / 'icons'};assets/icons",
            *qt_excludes,
            str(entry_script),
        ]
    )

    portable_exe = DIST / "WinOptiAI-Portable.exe"
    payload_dir = BUILD / "setup_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_exe = payload_dir / "WinOptiAI.exe"
    shutil.copy2(portable_exe, payload_exe)

    # 2. Build WinOptiAI-Setup.exe (self-contained graphical Windows installer)
    run_pyinstaller(
        [
            "--onefile",
            "--windowed",
            "--name", "WinOptiAI-Setup",
            "--icon", str(ico_path),
            "--add-data", f"{ROOT / 'VERSION'};.",
            "--add-data", f"{payload_exe};payload",
            *qt_excludes,
            str(ROOT / "packaging" / "installer_gui.py"),
        ]
    )

    setup_exe = DIST / "WinOptiAI-Setup.exe"
    write_sha256_manifest([portable_exe, setup_exe])
    print(f"Build complete:\n  {portable_exe}\n  {setup_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
