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
    bg: tuple[int, int, int, int] = (10, 15, 29, 255),
    rim: tuple[int, int, int, int] = (59, 130, 246, 255),
    accent: tuple[int, int, int, int] = (14, 165, 233, 255),
) -> None:
    """Draw the official TRODAI Hexa-Vault Sentinel octagonal app emblem at (x0, y0, size)."""
    def _pt(nx: float, ny: float, inset: float = 0.0, scale: float = 1.0) -> tuple[float, float]:
        px = x0 + (nx * scale + inset) * (size - 1) / 100.0
        py = y0 + (ny * scale + inset) * (size - 1) / 100.0
        return (px, py)

    # Outer octagonal container (#0A0F1D)
    outer_oct = [_pt(x, y) for x, y in ((16, 0), (84, 0), (100, 16), (100, 84), (84, 100), (16, 100), (0, 84), (0, 16))]
    draw.polygon(outer_oct, fill=bg)

    # Inner octagonal border (#3B82F6)
    inner_oct = [_pt(x, y) for x, y in ((19, 5), (81, 5), (95, 19), (95, 81), (81, 95), (19, 95), (5, 81), (5, 19))]
    rim_w = max(1, round(size * 0.025))
    draw.line([*inner_oct, inner_oct[0]], fill=rim, width=rim_w)

    # Inner TRODAI Hexa-Vault Sentinel strokes (#0EA5E9)
    k = 0.66
    off = 17.0
    sw = max(1, round(size * (0.055 if size <= 24 else 0.042)))

    if size <= 24:
        shield = [_pt(x, y, off, k) for x, y in ((50, 10), (78, 20), (90, 40), (80, 46), (80, 64), (50, 90), (20, 64), (20, 46), (10, 40), (22, 20))]
        draw.line([*shield, shield[0]], fill=accent, width=sw)
        muzzle = [_pt(x, y, off, k) for x, y in ((40, 56), (60, 56), (66, 72), (34, 72))]
        draw.line([*muzzle, muzzle[0]], fill=accent, width=sw)
        draw.line([_pt(30, 42, off, k), _pt(42, 42, off, k)], fill=accent, width=sw)
        draw.line([_pt(58, 42, off, k), _pt(70, 42, off, k)], fill=accent, width=sw)
        return

    shield = [_pt(x, y, off, k) for x, y in ((50, 8), (70, 14), (88, 30), (82, 40), (80, 66), (50, 92), (20, 66), (18, 40), (12, 30), (30, 14))]
    draw.line([*shield, shield[0]], fill=accent, width=sw)
    draw.line([_pt(30, 14, off, k), _pt(24, 36, off, k), _pt(18, 40, off, k)], fill=accent, width=sw)
    draw.line([_pt(70, 14, off, k), _pt(76, 36, off, k), _pt(82, 40, off, k)], fill=accent, width=sw)
    draw.line([_pt(38, 22, off, k), _pt(50, 28, off, k), _pt(62, 22, off, k)], fill=accent, width=sw)
    draw.line([_pt(42, 30, off, k), _pt(50, 34, off, k), _pt(58, 30, off, k)], fill=accent, width=sw)
    eye_l = [_pt(x, y, off, k) for x, y in ((32, 46), (38, 42), (44, 46), (38, 50))]
    eye_r = [_pt(x, y, off, k) for x, y in ((56, 46), (62, 42), (68, 46), (62, 50))]
    draw.line([*eye_l, eye_l[0]], fill=accent, width=sw)
    draw.line([*eye_r, eye_r[0]], fill=accent, width=sw)
    muzzle = [_pt(x, y, off, k) for x, y in ((40, 56), (60, 56), (66, 74), (34, 74))]
    draw.line([*muzzle, muzzle[0]], fill=accent, width=sw)
    nose = [_pt(x, y, off, k) for x, y in ((45, 60), (55, 60), (53, 65), (47, 65))]
    draw.line([*nose, nose[0]], fill=accent, width=max(1, sw - 1))
    draw.line([_pt(50, 65, off, k), _pt(50, 74, off, k)], fill=accent, width=sw)


def generate_app_icon() -> Path:
    """Generate high-contrast multi-resolution TRODAI octagonal .ico matching Hexa-Vault Sentinel."""
    ico_path = ASSETS / "icons" / "winoptiai.ico"
    sizes = [256, 128, 64, 48, 32, 16]
    images: list[Image.Image] = []

    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
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
    """Generate custom 0px TRODAI Obsidian Navy BMP banners for Inno Setup WizardImageFile & WizardSmallImageFile."""
    large_path = ASSETS / "icons" / "wizard_large.bmp"
    small_path = ASSETS / "icons" / "wizard_small.bmp"

    # Left sidebar graphic (164x314) in TRODAI Obsidian Navy (#0A0F1D) + Blueprint grid
    large = Image.new("RGB", (164, 314), (10, 15, 29))
    ld = ImageDraw.Draw(large)
    for gy in range(28, 314, 28):
        ld.line([(0, gy), (163, gy)], fill=(19, 30, 54), width=1)
    for gx in range(28, 164, 28):
        ld.line([(gx, 0), (gx, 313)], fill=(19, 30, 54), width=1)
    ld.rectangle([0, 0, 163, 313], outline=(51, 65, 95), width=1)

    emblem_rgba = Image.new("RGBA", (88, 88), (10, 15, 29, 255))
    _draw_brand_emblem(ImageDraw.Draw(emblem_rgba), 0, 0, 88)
    large.paste(emblem_rgba.convert("RGB"), (38, 68))

    # Minimalist TRODAI Cyber Cyan & Governance Blue accent bars below emblem
    ld.rectangle([38, 174, 125, 177], fill=(14, 165, 233))
    ld.rectangle([38, 184, 98, 186], fill=(59, 130, 246))
    large.save(large_path, format="BMP")

    # Header badge graphic (55x58) replacing default optical-disc icon
    small = Image.new("RGB", (55, 58), (10, 15, 29))
    sd = ImageDraw.Draw(small)
    emblem_sm = Image.new("RGBA", (42, 42), (10, 15, 29, 255))
    _draw_brand_emblem(ImageDraw.Draw(emblem_sm), 0, 0, 42)
    small.paste(emblem_sm.convert("RGB"), (6, 8))
    sd.rectangle([0, 0, 54, 57], outline=(59, 130, 246), width=1)
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
