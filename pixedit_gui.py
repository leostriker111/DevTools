#!/usr/bin/env python3
"""
pixedit_gui.py - editor de pixel art
Herramientas: lapiz, borrador, relleno, cuentagotas
Paletas: manual, teoria del color, extraccion desde URL
Formatos: .px (texto IA-friendly), .png
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import urllib.request
import io
import colorsys
import warnings
from pathlib import Path
from PIL import Image

warnings.filterwarnings("ignore", category=DeprecationWarning)

ZOOM_LEVELS = [2, 4, 6, 8, 10, 12, 16, 20, 24, 32]
DEFAULT_ZOOM = 20
CHECKER_A = "#C0C0C0"
CHECKER_B = "#808080"

DEFAULT_PALETTE = [
    "#000000", "#FFFFFF", "#FF0000", "#00FF00", "#0000FF",
    "#FFFF00", "#FF00FF", "#00FFFF", "#FF8000", "#8000FF",
    "#804000", "#008040", "#004080", "#FF8080", "#80FF80",
    "#8080FF",
]


# ── Utilidades de color ────────────────────────────────────────────────────

def hex_to_rgba(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)

def rgba_to_hex(rgba):
    r, g, b, _ = rgba
    return f"#{r:02X}{g:02X}{b:02X}"

def rgb_to_hls(hex_color):
    r, g, b, _ = hex_to_rgba(hex_color)
    return colorsys.rgb_to_hls(r/255, g/255, b/255)

def hls_to_hex(h, l, s):
    h = h % 1.0
    l = max(0.0, min(1.0, l))
    s = max(0.0, min(1.0, s))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

def theory_palette(base_hex, scheme):
    h, l, s = rgb_to_hls(base_hex)
    if scheme == "complementario":
        return [base_hex, hls_to_hex(h+0.5, l, s)]
    if scheme == "analogo":
        return [hls_to_hex(h-0.083, l, s), hls_to_hex(h-0.042, l, s),
                base_hex, hls_to_hex(h+0.042, l, s), hls_to_hex(h+0.083, l, s)]
    if scheme == "triadico":
        return [base_hex, hls_to_hex(h+1/3, l, s), hls_to_hex(h+2/3, l, s)]
    if scheme == "monocromatico":
        return [hls_to_hex(h, l*0.2, s), hls_to_hex(h, l*0.5, s), base_hex,
                hls_to_hex(h, 1-(1-l)*0.5, s), hls_to_hex(h, 1-(1-l)*0.2, s)]
    if scheme == "split_complementario":
        return [base_hex, hls_to_hex(h+0.5-0.083, l, s), hls_to_hex(h+0.5+0.083, l, s)]
    if scheme == "tetradico":
        return [base_hex, hls_to_hex(h+0.25, l, s),
                hls_to_hex(h+0.5, l, s), hls_to_hex(h+0.75, l, s)]
    return [base_hex]


# ── App ────────────────────────────────────────────────────────────────────

class PixEditApp:
    def __init__(self, root):
        self.root = root
        self.root.title("pixedit")

        self.W = 16
        self.H = 16
        self.zoom = DEFAULT_ZOOM
        self.pixels = [[(0, 0, 0, 0)] * self.W for _ in range(self.H)]
        self.rects = [[None] * self.W for _ in range(self.H)]
        self.palette = list(DEFAULT_PALETTE)
        self.current_color = "#000000"
        self.bg_color      = "#FFFFFF"
        self.current_tool = "lapiz"
        self.drawing = False
        self.last_cell = None

        # Vars (antes de build_ui para que los menus puedan referenciarlas)
        self.grid_var = tk.BooleanVar(value=True)
        self.bg_var = tk.StringVar(value="checker")

        self._build_ui()
        self._build_canvas()
        self._refresh_canvas()
        self._select_tool("lapiz")

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        menu = tk.Menu(self.root)
        self.root.config(menu=menu)

        fm = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Archivo", menu=fm)
        fm.add_command(label="Nuevo...",       command=self._cmd_new,       accelerator="Ctrl+N")
        fm.add_command(label="Abrir PNG",      command=self._cmd_open_png,  accelerator="Ctrl+O")
        fm.add_command(label="Abrir .px",      command=self._cmd_open_px)
        fm.add_separator()
        fm.add_command(label="Guardar PNG",    command=self._cmd_save_png,  accelerator="Ctrl+S")
        fm.add_command(label="Guardar .px",    command=self._cmd_save_px)
        fm.add_separator()
        fm.add_command(label="Exportar x2",    command=lambda: self._cmd_export(2))
        fm.add_command(label="Exportar x4",    command=lambda: self._cmd_export(4))
        fm.add_command(label="Exportar x8",    command=lambda: self._cmd_export(8))

        vm = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Vista", menu=vm)
        vm.add_command(label="Zoom +", command=self._zoom_in,  accelerator="+")
        vm.add_command(label="Zoom -", command=self._zoom_out, accelerator="-")
        vm.add_separator()
        vm.add_checkbutton(label="Grilla", variable=self.grid_var, command=self._refresh_canvas)

        self.root.bind("<Control-n>", lambda e: self._cmd_new())
        self.root.bind("<Control-o>", lambda e: self._cmd_open_png())
        self.root.bind("<Control-s>", lambda e: self._cmd_save_png())
        self.root.bind("<plus>",      lambda e: self._zoom_in())
        self.root.bind("<equal>",     lambda e: self._zoom_in())
        self.root.bind("<minus>",     lambda e: self._zoom_out())

        # Toolbar
        self.toolbar = tk.Frame(self.root, bd=1, relief=tk.SUNKEN)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self._build_toolbar()

        # Main area
        main = tk.Frame(self.root)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.left_panel = tk.Frame(main, width=130, bd=1, relief=tk.SUNKEN)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y)
        self.left_panel.pack_propagate(False)

        self.canvas_frame = tk.Frame(main, bg="#606060")
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.right_panel = tk.Frame(main, width=200, bd=1, relief=tk.SUNKEN)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_panel.pack_propagate(False)

        # Status
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(self.root, textvariable=self.status_var, anchor=tk.W,
                 bd=1, relief=tk.SUNKEN, font=("Courier", 9)).pack(side=tk.BOTTOM, fill=tk.X)

        self._build_left_panel()
        self._build_right_panel()

    def _build_toolbar(self):
        self.tool_buttons = {}
        for symbol, tool, tip in [
            ("L", "lapiz",       "Lapiz  [l]"),
            ("E", "borrador",    "Borrador  [e]"),
            ("F", "relleno",     "Relleno flood  [f]"),
            ("C", "cuentagotas", "Cuentagotas  [c]"),
        ]:
            btn = tk.Button(self.toolbar, text=symbol, width=3, font=("Courier", 10, "bold"),
                            command=lambda t=tool: self._select_tool(t))
            btn.pack(side=tk.LEFT, padx=2, pady=2)
            self.tool_buttons[tool] = btn

        _sep(self.toolbar)

        tk.Button(self.toolbar, text="Z+", command=self._zoom_in).pack(side=tk.LEFT, padx=1)
        tk.Button(self.toolbar, text="Z-", command=self._zoom_out).pack(side=tk.LEFT, padx=1)

        _sep(self.toolbar)

        tk.Checkbutton(self.toolbar, text="Grilla", variable=self.grid_var,
                       command=self._refresh_canvas).pack(side=tk.LEFT, padx=4)

        tk.Label(self.toolbar, text="Fondo:").pack(side=tk.LEFT, padx=4)
        for val, label in [("checker", "Trans"), ("white", "Blanco"), ("black", "Negro")]:
            tk.Radiobutton(self.toolbar, text=label, variable=self.bg_var,
                           value=val, command=self._refresh_canvas).pack(side=tk.LEFT)

        # Atajos de teclado para herramientas
        for key, tool in [("l", "lapiz"), ("e", "borrador"), ("f", "relleno"), ("c", "cuentagotas")]:
            self.root.bind(key, lambda evt, t=tool: self._select_tool(t))
        self.root.bind("x", lambda e: self._swap_colors())

    def _build_left_panel(self):
        tk.Label(self.left_panel, text="Colores", font=("Arial", 8, "bold")).pack(pady=(4,2))

        # Swatch FG / BG  (cuadro grande = BG, cuadro chico encima = FG)
        self.swatch_canvas = tk.Canvas(self.left_panel, width=100, height=76,
                                        bg=self.left_panel.cget("bg"),
                                        highlightthickness=0, cursor="hand2")
        self.swatch_canvas.pack()
        self.swatch_canvas.bind("<Button-1>", self._swatch_click)
        self._draw_swatch()

        # Botón intercambiar
        swap_row = tk.Frame(self.left_panel)
        swap_row.pack(pady=(0, 4))
        tk.Button(swap_row, text="FG<>BG", font=("Courier", 7),
                  command=self._swap_colors, relief=tk.FLAT, padx=2).pack(side=tk.LEFT)
        tk.Label(swap_row, text="[x]", font=("Courier", 7), fg="#888888").pack(side=tk.LEFT)

        frm = tk.Frame(self.left_panel)
        frm.pack(pady=4)

        self.r_var = tk.IntVar(value=0)
        self.g_var = tk.IntVar(value=0)
        self.b_var = tk.IntVar(value=0)
        for row, (var, label) in enumerate([(self.r_var, "R"), (self.g_var, "G"), (self.b_var, "B")]):
            tk.Label(frm, text=label, width=2, font=("Courier", 9)).grid(row=row, column=0)
            sb = tk.Spinbox(frm, from_=0, to=255, textvariable=var, width=5,
                            command=self._rgb_changed, font=("Courier", 9))
            sb.grid(row=row, column=1)
            sb.bind("<Return>", lambda e: self._rgb_changed())

        tk.Label(self.left_panel, text="Hex:").pack(pady=(6, 0))
        self.hex_var = tk.StringVar(value="#000000")
        hex_e = tk.Entry(self.left_panel, textvariable=self.hex_var, width=10, font=("Courier", 9))
        hex_e.pack()
        hex_e.bind("<Return>", self._hex_changed)

        tk.Button(self.left_panel, text="+ a paleta",
                  command=self._add_current_to_palette).pack(pady=6)

    def _build_right_panel(self):
        # Palette
        tk.Label(self.right_panel, text="PALETA", font=("Arial", 9, "bold")).pack(pady=4)

        self.palette_frame = tk.Frame(self.right_panel)
        self.palette_frame.pack(fill=tk.X, padx=4)
        self._refresh_palette_display()

        ttk.Separator(self.right_panel, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # Color theory
        tk.Label(self.right_panel, text="TEORIA DEL COLOR", font=("Arial", 9, "bold")).pack()

        self.scheme_var = tk.StringVar(value="complementario")
        schemes_frame = tk.Frame(self.right_panel)
        schemes_frame.pack(pady=2)
        for i, (label, val) in enumerate([
            ("Compl.",  "complementario"),
            ("Analogo", "analogo"),
            ("Triad.",  "triadico"),
            ("Mono",    "monocromatico"),
            ("Split",   "split_complementario"),
            ("Tetrad.", "tetradico"),
        ]):
            tk.Radiobutton(schemes_frame, text=label, variable=self.scheme_var,
                           value=val, font=("Arial", 8)).grid(row=i//2, column=i%2, sticky="w")

        tk.Button(self.right_panel, text="Generar",
                  command=self._generate_theory_palette).pack(pady=2)

        self.theory_frame = tk.Frame(self.right_panel, height=36)
        self.theory_frame.pack(fill=tk.X, padx=4, pady=2)

        ttk.Separator(self.right_panel, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # URL extractor
        tk.Label(self.right_panel, text="PALETA DESDE URL", font=("Arial", 9, "bold")).pack()

        self.url_var = tk.StringVar()
        tk.Entry(self.right_panel, textvariable=self.url_var, width=24,
                 font=("Courier", 8)).pack(padx=4, pady=2)

        nf = tk.Frame(self.right_panel)
        nf.pack()
        tk.Label(nf, text="Colores:").pack(side=tk.LEFT)
        self.url_n_var = tk.IntVar(value=8)
        tk.Spinbox(nf, from_=4, to=32, textvariable=self.url_n_var, width=4).pack(side=tk.LEFT)

        tk.Button(self.right_panel, text="Extraer paleta",
                  command=self._extract_url_palette).pack(pady=4)

    # ── Canvas ────────────────────────────────────────────────────────────

    def _build_canvas(self):
        self.h_scroll = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL)
        self.v_scroll = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT,  fill=tk.Y)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#606060",
                                xscrollcommand=self.h_scroll.set,
                                yscrollcommand=self.v_scroll.set,
                                cursor="crosshair")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.h_scroll.config(command=self.canvas.xview)
        self.v_scroll.config(command=self.canvas.yview)

        self.canvas.bind("<Button-1>",       self._mouse_down)
        self.canvas.bind("<B1-Motion>",      self._mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_up)
        self.canvas.bind("<Button-3>",       self._mouse_right)
        self.canvas.bind("<Motion>",         self._mouse_move)

    def _refresh_canvas(self):
        self.canvas.delete("all")
        self.rects = [[None] * self.W for _ in range(self.H)]

        tw = self.W * self.zoom
        th = self.H * self.zoom
        self.canvas.config(scrollregion=(0, 0, tw + 1, th + 1))

        for y in range(self.H):
            for x in range(self.W):
                self._draw_cell(x, y)

        if self.grid_var.get():
            self._draw_grid()

    def _cell_bg(self, x, y):
        mode = self.bg_var.get()
        if mode == "white":  return "#FFFFFF"
        if mode == "black":  return "#000000"
        checker_sz = max(1, self.zoom // 4)
        return CHECKER_A if ((x // checker_sz) + (y // checker_sz)) % 2 == 0 else CHECKER_B

    def _draw_cell(self, x, y):
        sx, sy = x * self.zoom, y * self.zoom
        ex, ey = sx + self.zoom, sy + self.zoom
        rgba = self.pixels[y][x]
        color = rgba_to_hex(rgba) if rgba[3] > 0 else self._cell_bg(x, y)

        if self.rects[y][x] is None:
            rid = self.canvas.create_rectangle(sx, sy, ex, ey, fill=color,
                                                outline="", tags="pixel")
            self.rects[y][x] = rid
        else:
            self.canvas.itemconfig(self.rects[y][x], fill=color)

    def _draw_grid(self):
        self.canvas.delete("grid")
        if not self.grid_var.get():
            return
        col = "#444444" if self.zoom >= 6 else "#555555"
        w_px, h_px = self.W * self.zoom, self.H * self.zoom
        for x in range(self.W + 1):
            sx = x * self.zoom
            self.canvas.create_line(sx, 0, sx, h_px, fill=col, tags="grid")
        for y in range(self.H + 1):
            sy = y * self.zoom
            self.canvas.create_line(0, sy, w_px, sy, fill=col, tags="grid")
        self.canvas.tag_raise("grid")

    # ── Mouse ─────────────────────────────────────────────────────────────

    def _canvas_cell(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        return int(cx / self.zoom), int(cy / self.zoom)

    def _mouse_down(self, event):
        self.drawing = True
        x, y = self._canvas_cell(event)
        if not self._in_bounds(x, y): return
        self.last_cell = (x, y)
        self._apply_tool(x, y)

    def _mouse_drag(self, event):
        if not self.drawing: return
        x, y = self._canvas_cell(event)
        if not self._in_bounds(x, y): return
        if (x, y) == self.last_cell: return
        if self.current_tool in ("lapiz", "borrador"):
            self._bresenham(self.last_cell[0], self.last_cell[1], x, y)
        self.last_cell = (x, y)

    def _mouse_up(self, event):
        self.drawing = False
        self.last_cell = None

    def _mouse_right(self, event):
        x, y = self._canvas_cell(event)
        if self._in_bounds(x, y):
            self._eyedropper(x, y)

    def _mouse_move(self, event):
        x, y = self._canvas_cell(event)
        if self._in_bounds(x, y):
            rgba = self.pixels[y][x]
            self.status_var.set(f"({x},{y})  rgba={rgba}  zoom={self.zoom}x")

    def _in_bounds(self, x, y):
        return 0 <= x < self.W and 0 <= y < self.H

    # ── Tools ─────────────────────────────────────────────────────────────

    def _select_tool(self, tool):
        self.current_tool = tool
        for t, btn in self.tool_buttons.items():
            btn.config(relief=tk.SUNKEN if t == tool else tk.RAISED,
                       bg="#AADDAA" if t == tool else "SystemButtonFace")
        self.status_var.set(f"Herramienta: {tool}")

    def _apply_tool(self, x, y):
        if   self.current_tool == "lapiz":       self._set_pixel(x, y, hex_to_rgba(self.current_color))
        elif self.current_tool == "borrador":     self._set_pixel(x, y, (0, 0, 0, 0))
        elif self.current_tool == "relleno":      self._flood_fill(x, y, hex_to_rgba(self.current_color))
        elif self.current_tool == "cuentagotas":  self._eyedropper(x, y)

    def _set_pixel(self, x, y, rgba):
        self.pixels[y][x] = rgba
        self._draw_cell(x, y)
        if self.grid_var.get():
            self.canvas.tag_raise("grid")

    def _eyedropper(self, x, y):
        rgba = self.pixels[y][x]
        if rgba[3] > 0:
            self._set_current_color(rgba_to_hex(rgba))

    def _bresenham(self, x0, y0, x1, y1):
        dx, dy = abs(x1-x0), abs(y1-y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self._apply_tool(x0, y0)
            if x0 == x1 and y0 == y1: break
            e2 = 2 * err
            if e2 > -dy: err -= dy; x0 += sx
            if e2 <  dx: err += dx; y0 += sy

    def _flood_fill(self, x, y, new_color):
        old_color = self.pixels[y][x]
        if old_color == new_color: return
        stack = [(x, y)]
        visited = set()
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited: continue
            if not self._in_bounds(cx, cy): continue
            if self.pixels[cy][cx] != old_color: continue
            visited.add((cx, cy))
            self.pixels[cy][cx] = new_color
            self._draw_cell(cx, cy)
            stack += [(cx+1,cy), (cx-1,cy), (cx,cy+1), (cx,cy-1)]
        if self.grid_var.get():
            self.canvas.tag_raise("grid")

    # ── Color ─────────────────────────────────────────────────────────────

    def _draw_swatch(self):
        c = self.swatch_canvas
        c.delete("all")
        bg = self.left_panel.cget("bg")
        # BG square (atras, abajo-derecha)
        c.create_rectangle(24, 22, 96, 74, fill=self.bg_color,
                           outline="white", width=2, tags="bg_sq")
        # FG square (adelante, arriba-izquierda)
        c.create_rectangle(4, 4, 76, 56, fill=self.current_color,
                           outline="white", width=2, tags="fg_sq")
        # Letras
        c.create_text(40, 30, text="FG", fill="white" if _is_dark(self.current_color) else "black",
                      font=("Courier", 8, "bold"), tags="fg_sq")
        c.create_text(72, 62, text="BG", fill="white" if _is_dark(self.bg_color) else "black",
                      font=("Courier", 7), tags="bg_sq")

    def _swatch_click(self, event):
        # Si el click está en la zona FG (arriba-izq) abre FG picker, si no BG
        if event.x < 76 and event.y < 56:
            self._pick_color_dialog()
        else:
            self._pick_bg_dialog()

    def _pick_bg_dialog(self, event=None):
        result = colorchooser.askcolor(color=self.bg_color, title="Color de fondo (BG)")
        if result[1]:
            self.bg_color = result[1].upper()
            self._draw_swatch()

    def _swap_colors(self):
        self.current_color, self.bg_color = self.bg_color, self.current_color
        self._draw_swatch()
        self.hex_var.set(self.current_color)
        r, g, b = hex_to_rgba(self.current_color)[:3]
        self.r_var.set(r); self.g_var.set(g); self.b_var.set(b)

    def _set_current_color(self, hex_color):
        self.current_color = hex_color.upper()
        self._draw_swatch()
        self.hex_var.set(self.current_color)
        r, g, b = hex_to_rgba(self.current_color)[:3]
        self.r_var.set(r); self.g_var.set(g); self.b_var.set(b)

    def _pick_color_dialog(self, event=None):
        result = colorchooser.askcolor(color=self.current_color, title="Color")
        if result[1]:
            self._set_current_color(result[1])

    def _rgb_changed(self):
        r, g, b = self.r_var.get(), self.g_var.get(), self.b_var.get()
        self._set_current_color(f"#{r:02X}{g:02X}{b:02X}")

    def _hex_changed(self, event=None):
        val = self.hex_var.get().strip()
        if not val.startswith("#"): val = "#" + val
        try:
            hex_to_rgba(val)  # validate
            self._set_current_color(val)
        except Exception:
            pass

    # ── Palette ───────────────────────────────────────────────────────────

    def _add_current_to_palette(self):
        if self.current_color not in self.palette:
            self.palette.append(self.current_color)
            self._refresh_palette_display()

    def _refresh_palette_display(self):
        for w in self.palette_frame.winfo_children():
            w.destroy()
        cols = 6
        for i, color in enumerate(self.palette):
            btn = tk.Button(self.palette_frame, bg=color, width=2, height=1, bd=1,
                            relief=tk.RAISED,
                            command=lambda c=color: self._set_current_color(c))
            btn.grid(row=i//cols, column=i%cols, padx=1, pady=1)
            btn.bind("<Button-3>", lambda e, c=color: self._remove_palette_color(c))

    def _remove_palette_color(self, color):
        if color in self.palette:
            self.palette.remove(color)
            self._refresh_palette_display()

    # ── Color theory ──────────────────────────────────────────────────────

    def _generate_theory_palette(self):
        colors = theory_palette(self.current_color, self.scheme_var.get())
        for w in self.theory_frame.winfo_children():
            w.destroy()
        for c in colors:
            tk.Button(self.theory_frame, bg=c, width=3, height=2,
                      command=lambda col=c: self._select_and_add(col)).pack(side=tk.LEFT, padx=1)
        tk.Button(self.theory_frame, text="+all",
                  command=lambda: self._add_all(colors)).pack(side=tk.LEFT, padx=2)

    def _select_and_add(self, color):
        self._set_current_color(color)
        if color not in self.palette:
            self.palette.append(color)
            self._refresh_palette_display()

    def _add_all(self, colors):
        for c in colors:
            if c not in self.palette:
                self.palette.append(c)
        self._refresh_palette_display()

    # ── URL palette extractor ─────────────────────────────────────────────

    def _extract_url_palette(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL vacia", "Escribe la URL de la imagen")
            return
        n = self.url_n_var.get()
        self.status_var.set("Descargando imagen...")
        self.root.update()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()

            img = Image.open(io.BytesIO(data)).convert("RGB")
            quantized = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
            raw = quantized.getpalette()[:n*3]

            added = 0
            for i in range(n):
                r, g, b = raw[i*3], raw[i*3+1], raw[i*3+2]
                c = f"#{r:02X}{g:02X}{b:02X}"
                if c not in self.palette:
                    self.palette.append(c)
                    added += 1

            self._refresh_palette_display()
            self.status_var.set(f"Paleta extraida — {added} colores nuevos")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo extraer:\n{e}")
            self.status_var.set("Error al extraer paleta")

    # ── Zoom ──────────────────────────────────────────────────────────────

    def _zoom_in(self):
        try:
            idx = ZOOM_LEVELS.index(self.zoom)
        except ValueError:
            idx = 0
        if idx < len(ZOOM_LEVELS) - 1:
            self.zoom = ZOOM_LEVELS[idx + 1]
            self._refresh_canvas()

    def _zoom_out(self):
        try:
            idx = ZOOM_LEVELS.index(self.zoom)
        except ValueError:
            idx = len(ZOOM_LEVELS) - 1
        if idx > 0:
            self.zoom = ZOOM_LEVELS[idx - 1]
            self._refresh_canvas()

    # ── File I/O ──────────────────────────────────────────────────────────

    def _cmd_new(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Nuevo")
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="Ancho:").grid(row=0, column=0, padx=8, pady=4)
        w_var = tk.IntVar(value=self.W)
        tk.Spinbox(dlg, from_=1, to=512, textvariable=w_var, width=6).grid(row=0, column=1)

        tk.Label(dlg, text="Alto:").grid(row=1, column=0, padx=8, pady=4)
        h_var = tk.IntVar(value=self.H)
        tk.Spinbox(dlg, from_=1, to=512, textvariable=h_var, width=6).grid(row=1, column=1)

        def ok():
            self.W, self.H = w_var.get(), h_var.get()
            self.pixels = [[(0,0,0,0)]*self.W for _ in range(self.H)]
            self._refresh_canvas()
            self.root.title("pixedit")
            dlg.destroy()

        tk.Button(dlg, text="Crear", command=ok).grid(row=2, column=0, columnspan=2, pady=8)
        dlg.wait_window()

    def _cmd_open_png(self):
        path = filedialog.askopenfilename(filetypes=[("PNG", "*.png"), ("Todos", "*.*")])
        if not path: return
        try:
            img = Image.open(path).convert("RGBA")
            self.W, self.H = img.size
            flat = list(img.getdata())
            self.pixels = [flat[y*self.W:(y+1)*self.W] for y in range(self.H)]
            self._refresh_canvas()
            self.root.title(f"pixedit — {Path(path).name}")
            self.status_var.set(f"Abierto: {self.W}x{self.H}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _cmd_save_png(self):
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png")])
        if not path: return
        self._save_png_to(path)

    def _save_png_to(self, path):
        img = Image.new("RGBA", (self.W, self.H))
        img.putdata([px for row in self.pixels for px in row])
        img.save(path)
        self.status_var.set(f"Guardado: {path}")

    def _cmd_open_px(self):
        path = filedialog.askopenfilename(filetypes=[("Pixel art text", "*.px"), ("Todos", "*.*")])
        if not path: return
        try:
            text = Path(path).read_text()
            w, h, flat = _parse_px(text)
            self.W, self.H = w, h
            self.pixels = [flat[y*w:(y+1)*w] for y in range(h)]
            self._refresh_canvas()
            self.root.title(f"pixedit — {Path(path).name}")
            self.status_var.set(f"Abierto .px: {w}x{h}")
        except Exception as e:
            messagebox.showerror("Error al abrir .px", str(e))

    def _cmd_save_px(self):
        path = filedialog.asksaveasfilename(defaultextension=".px",
                                            filetypes=[("Pixel art text", "*.px")])
        if not path: return
        try:
            text = _write_px(self.W, self.H, self.pixels)
            Path(path).write_text(text)
            self.status_var.set(f"Guardado .px: {path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _cmd_export(self, factor):
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png")])
        if not path: return
        img = Image.new("RGBA", (self.W, self.H))
        img.putdata([px for row in self.pixels for px in row])
        big = img.resize((self.W*factor, self.H*factor), Image.NEAREST)
        big.save(path)
        self.status_var.set(f"Exportado x{factor}: {self.W*factor}x{self.H*factor}")


# ── .px I/O ────────────────────────────────────────────────────────────────

def _parse_px(text):
    lines = text.splitlines()
    size_line = next(l for l in lines if l.startswith("size:"))
    w, h = map(int, size_line.split(":", 1)[1].strip().split("x"))

    palette, pixel_lines, section = {}, [], None
    for line in lines:
        s = line.strip()
        if s == "palette:":   section = "palette"; continue
        if s == "pixels:":    section = "pixels";  continue
        if section == "palette" and s:
            idx_s, col_s = s.split(":", 1)
            c = col_s.strip().lstrip("#")
            idx = int(idx_s.strip(), 16)
            if len(c) == 6:
                palette[idx] = (int(c[0:2],16), int(c[2:4],16), int(c[4:6],16), 255)
            else:
                palette[idx] = (int(c[0:2],16), int(c[2:4],16), int(c[4:6],16), int(c[6:8],16))
        elif section == "pixels" and s:
            pixel_lines.append(s)

    flat = []
    for line in pixel_lines:
        indices = [int(x,16) for x in line.split()] if " " in line else [int(c,16) for c in line]
        flat.extend(palette[i] for i in indices)

    if len(flat) != w*h:
        raise ValueError(f"Se esperaban {w*h} pixeles, se leyeron {len(flat)}")
    return w, h, flat

def _write_px(W, H, pixels):
    flat = [px for row in pixels for px in row]
    pal_list, pal_map = [], {}
    for px in flat:
        if px not in pal_map:
            pal_map[px] = len(pal_list)
            pal_list.append(px)

    compact = len(pal_list) <= 16
    lines = [f"size: {W}x{H}", "palette:"]
    for i, (r, g, b, a) in enumerate(pal_list):
        if a == 255:
            lines.append(f"  {i:X}: #{r:02X}{g:02X}{b:02X}")
        else:
            lines.append(f"  {i:X}: #{r:02X}{g:02X}{b:02X}{a:02X}")
    lines.append("pixels:")
    for y in range(H):
        row = flat[y*W:(y+1)*W]
        if compact:
            lines.append("".join(f"{pal_map[px]:X}" for px in row))
        else:
            lines.append(" ".join(f"{pal_map[px]:02X}" for px in row))
    return "\n".join(lines) + "\n"


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_dark(hex_color):
    r, g, b, _ = hex_to_rgba(hex_color)
    return (r * 0.299 + g * 0.587 + b * 0.114) < 128

def _sep(parent):
    tk.Frame(parent, width=2, bg="#AAAAAA", relief=tk.SUNKEN).pack(
        side=tk.LEFT, fill=tk.Y, padx=4, pady=2)


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1100x720")
    root.minsize(850, 550)
    PixEditApp(root)
    root.mainloop()
