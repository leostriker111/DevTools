#!/usr/bin/env python3
"""pixedit — pixel art via texto. encode/decode/preview/scale/info"""
import argparse
import subprocess
import sys
import warnings
from pathlib import Path
from PIL import Image

warnings.filterwarnings("ignore", category=DeprecationWarning)


# ─── formato .px ────────────────────────────────────────────────────────────
# size: WxH
# palette:
#   0: #RRGGBB[AA]
# pixels:
# <grilla de índices>
#   <=16 colores -> 1 char hex por pixel, sin espacios
#   17-256       -> 2 chars hex por pixel, separados por espacio
# ────────────────────────────────────────────────────────────────────────────


def _parse_color(s: str) -> tuple:
    s = s.strip().lstrip('#')
    if len(s) == 6:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        return (r, g, b, 255)
    elif len(s) == 8:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    raise ValueError(f"Color inválido: #{s}")


def encode(img_path: Path, out_path: Path = None):
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    pixels = list(img.getdata())

    palette_list = []
    palette_map = {}
    for px in pixels:
        if px not in palette_map:
            palette_map[px] = len(palette_list)
            palette_list.append(px)

    if len(palette_list) > 256:
        print(f"Advertencia: {len(palette_list)} colores únicos — considera reducir la paleta primero")

    compact = len(palette_list) <= 16
    out_path = out_path or img_path.with_suffix(".px")

    with open(out_path, "w") as f:
        f.write(f"size: {w}x{h}\n")
        f.write("palette:\n")
        for i, (r, g, b, a) in enumerate(palette_list):
            if a == 255:
                f.write(f"  {i:X}: #{r:02X}{g:02X}{b:02X}\n")
            else:
                f.write(f"  {i:X}: #{r:02X}{g:02X}{b:02X}{a:02X}\n")
        f.write("pixels:\n")
        for y in range(h):
            row = pixels[y * w : (y + 1) * w]
            if compact:
                line = "".join(f"{palette_map[px]:X}" for px in row)
            else:
                line = " ".join(f"{palette_map[px]:02X}" for px in row)
            f.write(line + "\n")

    mode = "compacto" if compact else "extendido"
    print(f"OK {w}x{h} | {len(palette_list)} colores | modo {mode} -> {out_path}")


def decode(px_path: Path, out_path: Path = None):
    text = Path(px_path).read_text()
    lines = text.splitlines()

    size_line = next((l for l in lines if l.startswith("size:")), None)
    if not size_line:
        sys.exit("Error: falta línea 'size:'")
    w, h = map(int, size_line.split(":", 1)[1].strip().split("x"))

    palette = {}
    pixel_lines = []
    section = None

    for line in lines:
        stripped = line.strip()
        if stripped == "palette:":
            section = "palette"
            continue
        if stripped == "pixels:":
            section = "pixels"
            continue
        if section == "palette" and stripped:
            idx_str, color_str = stripped.split(":", 1)
            palette[int(idx_str.strip(), 16)] = _parse_color(color_str.strip())
        elif section == "pixels" and stripped:
            pixel_lines.append(stripped)

    pixels = []
    for line in pixel_lines:
        if " " in line:
            indices = [int(x, 16) for x in line.split()]
        else:
            indices = [int(c, 16) for c in line]
        for idx in indices:
            if idx not in palette:
                sys.exit(f"Error: índice {idx:X} no está en la paleta")
            pixels.append(palette[idx])

    if len(pixels) != w * h:
        sys.exit(f"Error: se esperaban {w*h} píxeles, se leyeron {len(pixels)}")

    img = Image.new("RGBA", (w, h))
    img.putdata(pixels)

    out_path = out_path or Path(px_path).with_suffix(".png")
    img.save(out_path)
    print(f"OK {w}x{h} -> {out_path}")


def preview(img_path: Path, scale: int = 8):
    img = Image.open(img_path)
    w, h = img.size
    big = img.resize((w * scale, h * scale), Image.NEAREST)
    print(f"Previsualizando {w}x{h} a escala ×{scale} ({w*scale}x{h*scale})")
    big.show()


def scale_img(img_path: Path, factor: int, out_path: Path = None):
    img = Image.open(img_path)
    w, h = img.size
    big = img.resize((w * factor, h * factor), Image.NEAREST)
    out_path = out_path or Path(img_path).with_name(
        Path(img_path).stem + f"_x{factor}" + Path(img_path).suffix
    )
    big.save(out_path)
    print(f"OK {w}x{h} -> {w*factor}x{h*factor} -> {out_path}")


def info(img_path: Path):
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    pixels = list(img.getdata())
    colors = set(pixels)
    transparent = sum(1 for _, _, _, a in pixels if a == 0)
    semi = sum(1 for _, _, _, a in pixels if 0 < a < 255)

    print(f"Archivo   : {img_path}")
    print(f"Tamaño    : {w}x{h}  ({w*h} píxeles)")
    print(f"Colores   : {len(colors)} únicos")
    if transparent:
        print(f"Alfa=0    : {transparent} px ({100*transparent//(w*h)}%)")
    if semi:
        print(f"Semi-alfa : {semi} px")
    compact_ok = len(colors) <= 16
    print(f"Formato   : {'compacto (1 char/px)' if compact_ok else 'extendido (2 chars/px)'}")


def palette_cmd(img_path: Path):
    img = Image.open(img_path).convert("RGBA")
    pixels = list(img.getdata())
    seen = {}
    order = []
    for px in pixels:
        if px not in seen:
            seen[px] = len(order)
            order.append(px)
    print(f"{len(order)} colores en {img_path}:")
    for i, (r, g, b, a) in enumerate(order):
        alpha = f" a={a}" if a != 255 else ""
        if a == 255:
            print(f"  {i:>3X}: #{r:02X}{g:02X}{b:02X}{alpha}")
        else:
            print(f"  {i:>3X}: #{r:02X}{g:02X}{b:02X}{a:02X}")


def launch_gui(file_path: Path = None):
    gui_script = Path(__file__).parent / "pixedit_gui.py"
    if not gui_script.exists():
        sys.exit(f"Error: no encuentro pixedit_gui.py en {gui_script.parent}")
    cmd = [sys.executable, str(gui_script)]
    if file_path:
        cmd.append(str(file_path))
    subprocess.Popen(cmd)
    print(f"GUI abierta{' con ' + str(file_path) if file_path else ''}")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="pixedit — pixel art <-> texto",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
comandos:
  gui     [archivo]           abre el editor grafico (opcional: archivo .px o .png)
  encode  sprite.png          PNG  -> sprite.px (texto editable)
  decode  sprite.px           .px  -> PNG
  preview sprite.png [escala] muestra ventana ampliada (default x8)
  scale   sprite.png factor   escala con nearest-neighbor
  info    sprite.png          dimensiones y colores
  palette sprite.png          lista la paleta
        """,
    )
    p.add_argument("cmd", choices=["gui", "encode", "decode", "preview", "scale", "info", "palette"])
    p.add_argument("file", type=Path, nargs="?", help="archivo de entrada")
    p.add_argument("extra", nargs="?", help="parametro extra: output path o escala")

    args = p.parse_args()

    if args.cmd == "gui":
        launch_gui(args.file)
        return

    if not args.file:
        sys.exit("Error: falta el archivo")
    if not args.file.exists():
        sys.exit(f"Error: no existe {args.file}")

    if args.cmd == "encode":
        encode(args.file, Path(args.extra) if args.extra else None)
    elif args.cmd == "decode":
        decode(args.file, Path(args.extra) if args.extra else None)
    elif args.cmd == "preview":
        scale = int(args.extra) if args.extra else 8
        preview(args.file, scale)
    elif args.cmd == "scale":
        if not args.extra:
            sys.exit("Falta el factor de escala. Ej: pixedit scale sprite.png 4")
        scale_img(args.file, int(args.extra))
    elif args.cmd == "info":
        info(args.file)
    elif args.cmd == "palette":
        palette_cmd(args.file)


if __name__ == "__main__":
    main()
