"""Build script for WinOptiAI-Portable.exe, WinOptiAI-Setup.exe (Inno Setup 6), and SHA256SUMS.txt."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def read_version() -> str:
    vf = ROOT / "VERSION"
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "0.1.0"


def find_iscc() -> Path | None:
    """Locate Inno Setup 6 compiler (ISCC.exe) across standard Windows install paths."""
    in_path = shutil.which("iscc") or shutil.which("ISCC.exe")
    if in_path:
        return Path(in_path)

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _draw_brand_emblem(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    size: int,
    *,
    bg: tuple[int, int, int, int] = (15, 20, 27, 255),
    rim: tuple[int, int, int, int] = (118, 146, 176, 255),
    ink: tuple[int, int, int, int] = (244, 247, 250, 255),
    accent: tuple[int, int, int, int] = (142, 179, 214, 255),
) -> None:
    """Draw the sharp 0px WinOptiAI architectural emblem at (x0, y0, size)."""
    draw.rectangle([x0, y0, x0 + size - 1, y0 + size - 1], fill=bg, outline=rim, width=max(1, size // 16))
    pad = max(2, round(size * 0.19))
    stroke = max(1, round(size * 0.085))
    bx0, by0 = x0 + pad, y0 + pad
    bx1, by1 = x0 + size - pad - 1, y0 + size - pad - 1
    draw.rectangle([bx0, by0, bx1, by1], outline=ink, width=stroke)

    split_x = x0 + round(size * 0.44)
    split_y = y0 + round(size * 0.44)
    draw.line([(bx0, split_y), (bx1, split_y)], fill=ink, width=stroke)
    draw.line([(split_x, split_y), (split_x, by1)], fill=ink, width=stroke)

    inner_off = max(2, round(size * 0.09))
    ax0, ay0 = split_x + inner_off, split_y + inner_off
    ax1, ay1 = bx1 - inner_off, by1 - inner_off
    if ax1 > ax0 and ay1 > ay0:
        draw.rectangle([ax0, ay0, ax1, ay1], fill=accent)


def generate_app_icon() -> Path:
    """Generate high-contrast multi-resolution geometric 0px Windows .ico matching brand.svg."""
    ico_path = ASSETS / "icons" / "winoptiai.ico"
    sizes = [256, 128, 64, 48, 32, 16]
    images: list[Image.Image] = []

    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (15, 20, 27, 255))
        draw = ImageDraw.Draw(img)
        _draw_brand_emblem(draw, 0, 0, sz)
        images.append(img)

    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    return ico_path


def generate_installer_wizard_images() -> tuple[Path, Path]:
    """Generate custom 0px Obsidian Acrylic BMP banners for Inno Setup WizardImageFile & WizardSmallImageFile."""
    large_path = ASSETS / "icons" / "wizard_large.bmp"
    small_path = ASSETS / "icons" / "wizard_small.bmp"

    # Left sidebar graphic (164x314)
    large = Image.new("RGB", (164, 314), (12, 16, 22))
    ld = ImageDraw.Draw(large)
    for gy in range(28, 314, 28):
        ld.line([(0, gy), (163, gy)], fill=(23, 29, 39), width=1)
    for gx in range(28, 164, 28):
        ld.line([(gx, 0), (gx, 313)], fill=(20, 26, 35), width=1)
    ld.rectangle([0, 0, 163, 313], outline=(48, 60, 76), width=1)

    emblem_rgba = Image.new("RGBA", (84, 84), (15, 20, 27, 255))
    _draw_brand_emblem(ImageDraw.Draw(emblem_rgba), 0, 0, 84)
    large.paste(emblem_rgba.convert("RGB"), (40, 72))

    # Minimalist geometric accent bar below emblem
    ld.rectangle([40, 174, 123, 177], fill=(142, 179, 214))
    ld.rectangle([40, 184, 96, 186], fill=(95, 114, 138))
    large.save(large_path, format="BMP")

    # Header badge graphic (55x58) replacing default optical-disc icon
    small = Image.new("RGB", (55, 58), (15, 20, 27))
    sd = ImageDraw.Draw(small)
    emblem_sm = Image.new("RGBA", (42, 42), (15, 20, 27, 255))
    _draw_brand_emblem(ImageDraw.Draw(emblem_sm), 0, 0, 42)
    small.paste(emblem_sm.convert("RGB"), (6, 8))
    sd.rectangle([0, 0, 54, 57], outline=(62, 78, 98), width=1)
    small.save(small_path, format="BMP")

    return large_path, small_path


def find_signtool() -> Path | None:
    """Locate Windows SDK signtool.exe if Authenticode signing is configured."""
    found = shutil.which("signtool") or shutil.which("signtool.exe")
    if found:
        return Path(found)
    kits_root = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if kits_root.exists():
        for exe in sorted(kits_root.rglob("x64/signtool.exe"), reverse=True):
            return exe
    return None


def maybe_sign_binary(binary: Path) -> None:
    """Sign executable with Authenticode when WINOPTIAI_SIGN_PFX or WINOPTIAI_SIGN_SHA1 is set."""
    pfx = os.environ.get("WINOPTIAI_SIGN_PFX", "").strip()
    sha1 = os.environ.get("WINOPTIAI_SIGN_SHA1", "").strip()
    if not pfx and not sha1:
        return
    signtool = find_signtool()
    if signtool is None:
        print(f"Advertencia: firma configurada pero signtool.exe no encontrado; {binary.name} queda sin firmar.")
        return

    cmd = [
        str(signtool),
        "sign",
        "/fd",
        "SHA256",
        "/tr",
        os.environ.get("WINOPTIAI_SIGN_TSA", "http://timestamp.digicert.com"),
        "/td",
        "SHA256",
    ]
    if pfx:
        cmd.extend(["/f", pfx])
        pwd = os.environ.get("WINOPTIAI_SIGN_PASS", "").strip()
        if pwd:
            cmd.extend(["/p", pwd])
    else:
        cmd.extend(["/sha1", sha1])
    cmd.append(str(binary))
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"signtool failed for {binary.name} (exit {res.returncode})")
    print(f"Firmado Authenticode OK: {binary.name}")


def run_pyinstaller(args: list[str]) -> None:
    # Ensure Python's own DLLs (libssl-3-x64.dll, libcrypto-3-x64.dll) precede external PATH tools like PHP
    env = os.environ.copy()
    py_dlls = str(Path(sys.base_prefix) / "DLLs")
    py_base = str(Path(sys.base_prefix))
    env["PATH"] = f"{py_dlls};{py_base};{env.get('PATH', '')}"

    extra_ssl: list[str] = []
    for dll_name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        dll_path = Path(py_dlls) / dll_name
        if dll_path.exists():
            extra_ssl.extend(["--add-binary", f"{dll_path};."])

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", *extra_ssl, *args]
    res = subprocess.run(cmd, cwd=str(ROOT), env=env)
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
    version = read_version()
    ico_path = generate_app_icon()
    generate_installer_wizard_images()

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

    work_dir = Path(os.environ.get("TEMP", str(BUILD))) / "winoptiai_pyi_build"
    work_dir.mkdir(parents=True, exist_ok=True)

    run_pyinstaller(
        [
            "--onefile",
            "--windowed",
            "--name", "WinOptiAI-Portable",
            "--icon", str(ico_path),
            "--workpath", str(work_dir),
            "--paths", str(ROOT / "src"),
            "--add-data", f"{ROOT / 'VERSION'};.",
            "--add-data", f"{ASSETS / 'fonts'};assets/fonts",
            "--add-data", f"{ASSETS / 'icons'};assets/icons",
            *qt_excludes,
            str(entry_script),
        ]
    )

    portable_exe = DIST / "WinOptiAI-Portable.exe"
    setup_exe = DIST / "WinOptiAI-Setup.exe"
    maybe_sign_binary(portable_exe)

    # 2. Build WinOptiAI-Setup.exe (prefer native Inno Setup 6 wizard)
    iscc = find_iscc()
    if iscc is not None:
        iss_file = ROOT / "packaging" / "installer.iss"
        res = subprocess.run(
            [str(iscc), f"/DMyAppVersion={version}", str(iss_file)],
            cwd=str(ROOT),
        )
        if res.returncode != 0:
            raise RuntimeError(f"ISCC failed with exit code {res.returncode}")
    else:
        payload_dir = BUILD / "setup_payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_exe = payload_dir / "WinOptiAI.exe"
        shutil.copy2(portable_exe, payload_exe)
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

    maybe_sign_binary(setup_exe)
    write_sha256_manifest([portable_exe, setup_exe])
    print(f"Build complete (v{version}):\n  {portable_exe}\n  {setup_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
