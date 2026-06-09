#!/usr/bin/env python3
"""
audiodit_gui.py — editor de audio multitrack
Carga pistas, ajusta vol/pan, aplica efectos, exporta mezcla
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import tempfile
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import warnings
warnings.filterwarnings("ignore")

try:
    from pydub import AudioSegment
    from pydub.effects import normalize as pydub_normalize
except ImportError:
    sys.exit("pip install pydub")

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

WAVE_COLOR   = "#33CC66"
WAVE_BG      = "#1A1A2E"
TRACK_H      = 90
TIMELINE_H   = 24
TRACK_CTRL_W = 220

# ── Teclado piano: layout físico ──────────────────────────────────────────
#   Teclas blancas: A S D F G H J K L  (+ E5 sin tecla asignada)
#   Teclas negras:  W E _ T Y U _ O P
#
#   Indice visual: 0  1  2  3  4  5  6  7  8  9
#   Nota:          C4 D4 E4 F4 G4 A4 B4 C5 D5 E5
#   Tecla compu:   a  s  d  f  g  h  j  k  l  --
#
#   Negras (posición = índice del blanco izquierdo + 0.5):
#   0.5=C#4/w  1.5=D#4/e  3.5=F#4/t  4.5=G#4/y  5.5=A#4/u  7.5=C#5/o  8.5=D#5/p

WHITE_KEYS = [
    (0, 'a', 'C4',  261.63),
    (1, 's', 'D4',  293.66),
    (2, 'd', 'E4',  329.63),
    (3, 'f', 'F4',  349.23),
    (4, 'g', 'G4',  392.00),
    (5, 'h', 'A4',  440.00),
    (6, 'j', 'B4',  493.88),
    (7, 'k', 'C5',  523.25),
    (8, 'l', 'D5',  587.33),
    (9, '',  'E5',  659.26),   # visual solamente
]
BLACK_KEYS = [
    (0.5, 'w', 'C#4', 277.18),
    (1.5, 'e', 'D#4', 311.13),
    (3.5, 't', 'F#4', 369.99),
    (4.5, 'y', 'G#4', 415.30),
    (5.5, 'u', 'A#4', 466.16),
    (7.5, 'o', 'C#5', 554.37),
    (8.5, 'p', 'D#5', 622.25),
]
_ALL_KEYS = {k[1]: k for k in WHITE_KEYS + BLACK_KEYS if k[1]}  # key -> (idx,key,note,freq)

WKW, WKH = 48, 126   # white key width / height
BKW, BKH = 30, 76    # black key width / height
PIANO_PAD = 6        # left padding


# ── Sintetizador ──────────────────────────────────────────────────────────

class PianoSynth:
    SR = 44100

    def __init__(self):
        self._notes: dict = {}
        self._lock  = threading.Lock()
        self._stream = sd.OutputStream(
            samplerate=self.SR, channels=1, blocksize=512, dtype='float32',
            callback=self._callback)
        self._stream.start()

    def _callback(self, out, frames, t, status):
        buf = np.zeros(frames, dtype=np.float32)
        with self._lock:
            done = []
            for freq, (s, pos) in self._notes.items():
                end = min(pos + frames, len(s))
                chunk = s[pos:end]
                buf[:len(chunk)] += chunk
                if end >= len(s): done.append(freq)
                else: self._notes[freq] = (s, end)
            for f in done: del self._notes[f]
        peak = np.abs(buf).max()
        if peak > 0.92: buf *= 0.92 / peak
        out[:, 0] = buf

    def note_on(self, freq: float):
        dur = 1.8
        n = int(self.SR * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        # Piano-like: fundamental + armónicos con decaimiento natural
        w  = (np.sin(2*np.pi*freq*t)
            + 0.45*np.sin(4*np.pi*freq*t)
            + 0.22*np.sin(6*np.pi*freq*t)
            + 0.10*np.sin(8*np.pi*freq*t)
            + 0.05*np.sin(10*np.pi*freq*t))
        att = int(0.008 * self.SR)
        rel = int(0.9  * self.SR)
        env = np.ones(n)
        env[:att] = np.linspace(0, 1, att)
        env[-rel:] *= np.linspace(1, 0, rel)
        w = (w * env * 0.55).astype(np.float32)
        with self._lock:
            self._notes[freq] = (w, 0)

    def note_off(self, freq: float):
        with self._lock:
            if freq in self._notes:
                s, pos = self._notes[freq]
                fade = min(int(0.06 * self.SR), len(s) - pos)
                if fade > 0:
                    s[pos:pos+fade] *= np.linspace(1, 0, fade)
                if pos + fade < len(s):
                    s[pos+fade:] = 0.0

    def close(self):
        self._stream.stop()
        self._stream.close()


# ── Grabador de micrófono ─────────────────────────────────────────────────

class Recorder:
    SR = 44100

    def __init__(self):
        self._chunks: list = []
        self._active = False
        self._stream = None

    def start(self):
        self._chunks = []
        self._active = True
        self._stream = sd.InputStream(
            samplerate=self.SR, channels=1, dtype='float32',
            callback=self._cb)
        self._stream.start()

    def _cb(self, indata, frames, t, status):
        if self._active:
            self._chunks.append(indata.copy())

    def stop(self) -> Optional[np.ndarray]:
        self._active = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._chunks:
            return None
        return np.concatenate(self._chunks, axis=0).squeeze()

    def save(self, path: str) -> bool:
        data = self.stop()
        if data is None or len(data) == 0:
            return False
        import soundfile as sf
        sf.write(path, data, self.SR)
        return True


# ── Modelo ────────────────────────────────────────────────────────────────

@dataclass
class Track:
    name: str
    path: Path
    audio: AudioSegment
    volume_db: float   = 0.0
    muted: bool        = False
    solo:  bool        = False
    offset_s: float    = 0.0
    fade_in_s: float   = 0.0
    fade_out_s: float  = 0.0
    reverb: float      = 0.0
    bass_db: float     = 0.0
    treble_db: float   = 0.0
    # runtime
    wave_cache: list   = field(default_factory=list, repr=False)


def _build_mix(tracks: list[Track]) -> Optional[AudioSegment]:
    active = [t for t in tracks if not t.muted]
    solos  = [t for t in active if t.solo]
    if solos: active = solos
    if not active: return None

    def process(t: Track) -> tuple[AudioSegment, int]:
        a = t.audio + t.volume_db
        if t.fade_in_s  > 0: a = a.fade_in(int(t.fade_in_s  * 1000))
        if t.fade_out_s > 0: a = a.fade_out(int(t.fade_out_s * 1000))
        if t.reverb > 0:
            delay = max(15, int(t.reverb * 120))
            result = a
            for i in range(1, 5):
                from pydub import AudioSegment as AS
                ghost = (AS.silent(duration=delay*i) + a) - (4*i)
                result = result.overlay(ghost[:len(result)])
            a = result
        if t.bass_db or t.treble_db:
            try:
                from pydub.scipy_effects import low_pass_filter, high_pass_filter
                if t.bass_db:   a = a.overlay(low_pass_filter(t.audio,  300) + t.bass_db)
                if t.treble_db: a = a.overlay(high_pass_filter(t.audio, 4000) + t.treble_db)
            except ImportError:
                pass
        return a, int(t.offset_s * 1000)

    results = [process(t) for t in active]
    max_dur = max(offset + len(a) for a, offset in results)
    mix = AudioSegment.silent(duration=max_dur, frame_rate=44100).set_channels(2)
    for a, offset in results:
        mix = mix.overlay(a, position=offset)
    return mix


def _waveform_points(audio: AudioSegment, width: int, height: int) -> list:
    if not HAS_NP or width <= 0:
        return []
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
    if audio.channels == 2:
        samples = samples[::2]
    peak = np.abs(samples).max()
    if peak == 0:
        return []
    samples /= peak
    mid = height // 2
    chunk = max(1, len(samples) // width)
    pts = []
    for i in range(min(width, len(samples) // chunk)):
        seg = samples[i*chunk:(i+1)*chunk]
        h = int(np.abs(seg).max() * (mid - 2))
        pts.append((i, mid - h, mid + h))
    return pts


# ── Widgets ───────────────────────────────────────────────────────────────

class TrackRow(tk.Frame):
    def __init__(self, parent, track: Track, app, **kw):
        super().__init__(parent, bg="#2D2D3D", relief=tk.RIDGE, bd=1, **kw)
        self.track = track
        self.app   = app
        self._build()

    def _build(self):
        # Left controls
        ctrl = tk.Frame(self, bg="#2D2D3D", width=TRACK_CTRL_W)
        ctrl.pack(side=tk.LEFT, fill=tk.Y)
        ctrl.pack_propagate(False)

        # Name (editable)
        self.name_var = tk.StringVar(value=self.track.name)
        ne = tk.Entry(ctrl, textvariable=self.name_var, bg="#1A1A2E", fg="#EEEEFF",
                      font=("Courier", 9), relief=tk.FLAT, width=18)
        ne.pack(side=tk.TOP, padx=4, pady=(4,0))
        ne.bind("<Return>", lambda e: setattr(self.track, "name", self.name_var.get()))

        # Buttons row
        btn_row = tk.Frame(ctrl, bg="#2D2D3D")
        btn_row.pack(side=tk.TOP, fill=tk.X, padx=4, pady=2)

        self.mute_var = tk.BooleanVar(value=self.track.muted)
        tk.Checkbutton(btn_row, text="M", variable=self.mute_var, bg="#2D2D3D",
                       fg="#FFAA00", selectcolor="#442200", activebackground="#2D2D3D",
                       command=self._toggle_mute, font=("Courier", 8, "bold")).pack(side=tk.LEFT)

        self.solo_var = tk.BooleanVar(value=self.track.solo)
        tk.Checkbutton(btn_row, text="S", variable=self.solo_var, bg="#2D2D3D",
                       fg="#00CCFF", selectcolor="#002244", activebackground="#2D2D3D",
                       command=self._toggle_solo, font=("Courier", 8, "bold")).pack(side=tk.LEFT, padx=2)

        tk.Button(btn_row, text="FX", bg="#333355", fg="#AAAAFF",
                  font=("Courier", 8), relief=tk.FLAT,
                  command=lambda: self.app.open_fx_panel(self)).pack(side=tk.LEFT, padx=2)

        tk.Button(btn_row, text="X", bg="#441111", fg="#FF6666",
                  font=("Courier", 8), relief=tk.FLAT,
                  command=lambda: self.app.remove_track(self)).pack(side=tk.RIGHT)

        # Volume slider
        vol_row = tk.Frame(ctrl, bg="#2D2D3D")
        vol_row.pack(side=tk.TOP, fill=tk.X, padx=4)
        tk.Label(vol_row, text="Vol", bg="#2D2D3D", fg="#888888",
                 font=("Courier", 8)).pack(side=tk.LEFT)
        self.vol_var = tk.DoubleVar(value=self.track.volume_db)
        sl = tk.Scale(vol_row, variable=self.vol_var, from_=-20, to=20, resolution=0.5,
                      orient=tk.HORIZONTAL, length=140, bg="#2D2D3D", fg="#AAFFAA",
                      troughcolor="#111122", sliderlength=12, showvalue=False,
                      command=self._vol_changed)
        sl.pack(side=tk.LEFT)
        self.vol_label = tk.Label(vol_row, text="0.0", bg="#2D2D3D", fg="#AAFFAA",
                                   font=("Courier", 8), width=5)
        self.vol_label.pack(side=tk.LEFT)

        # Waveform canvas
        self.wave_canvas = tk.Canvas(self, bg=WAVE_BG, height=TRACK_H, cursor="arrow",
                                      highlightthickness=0)
        self.wave_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.wave_canvas.bind("<Configure>", self._on_resize)
        self._draw_wave()

    def _toggle_mute(self):
        self.track.muted = self.mute_var.get()

    def _toggle_solo(self):
        self.track.solo = self.solo_var.get()

    def _vol_changed(self, val=None):
        self.track.volume_db = self.vol_var.get()
        self.vol_label.config(text=f"{self.track.volume_db:+.1f}")

    def _on_resize(self, event):
        self._draw_wave()

    def _draw_wave(self):
        c = self.wave_canvas
        c.delete("all")
        w = c.winfo_width()  or 400
        h = c.winfo_height() or TRACK_H

        if not self.track.wave_cache or len(self.track.wave_cache) != w:
            self.track.wave_cache = _waveform_points(self.track.audio, w, h)

        # Fondo con linea central
        c.create_line(0, h//2, w, h//2, fill="#333344")

        for x, top, bot in self.track.wave_cache:
            c.create_line(x, top, x, bot, fill=WAVE_COLOR)

        # Nombre del archivo
        c.create_text(6, 6, anchor="nw", text=self.track.path.name,
                      fill="#555566", font=("Courier", 8))

    def refresh_wave(self):
        self.track.wave_cache = []
        self._draw_wave()


# ── FX Panel ──────────────────────────────────────────────────────────────

class FXPanel(tk.Toplevel):
    def __init__(self, parent, track_row: TrackRow):
        super().__init__(parent)
        self.track_row = track_row
        self.t = track_row.track
        self.title(f"FX — {self.t.name}")
        self.resizable(False, False)
        self.configure(bg="#1A1A2E")
        self._build()

    def _lbl(self, parent, text):
        return tk.Label(parent, text=text, bg="#1A1A2E", fg="#AAAACC",
                        font=("Courier", 9), width=12, anchor="w")

    def _slider(self, parent, from_, to, val, cmd, res=0.05):
        v = tk.DoubleVar(value=val)
        f = tk.Frame(parent, bg="#1A1A2E")
        s = tk.Scale(f, variable=v, from_=from_, to=to, resolution=res,
                     orient=tk.HORIZONTAL, length=200, bg="#1A1A2E", fg="#CCCCFF",
                     troughcolor="#111133", sliderlength=14, showvalue=True,
                     command=cmd)
        s.pack()
        return f, v

    def _build(self):
        p = tk.Frame(self, bg="#1A1A2E", padx=12, pady=10)
        p.pack()

        def row(label, from_, to, attr, res=0.1):
            r = tk.Frame(p, bg="#1A1A2E")
            r.pack(fill=tk.X, pady=3)
            self._lbl(r, label).pack(side=tk.LEFT)
            v = tk.DoubleVar(value=getattr(self.t, attr))
            sl = tk.Scale(r, variable=v, from_=from_, to=to, resolution=res,
                          orient=tk.HORIZONTAL, length=180, bg="#1A1A2E", fg="#CCCCFF",
                          troughcolor="#111133", sliderlength=14, showvalue=True,
                          command=lambda val, a=attr, vv=v: setattr(self.t, a, vv.get()))
            sl.pack(side=tk.LEFT)

        row("Reverb (0-1)",  0.0,  1.0, "reverb",     res=0.05)
        row("Bass (dB)",    -12.0, 12.0, "bass_db",    res=0.5)
        row("Treble (dB)",  -12.0, 12.0, "treble_db",  res=0.5)
        row("Fade in  (s)",  0.0,  10.0, "fade_in_s",  res=0.1)
        row("Fade out (s)",  0.0,  10.0, "fade_out_s", res=0.1)
        row("Offset (s)",    0.0,  30.0, "offset_s",   res=0.1)

        tk.Button(p, text="Resetear efectos", bg="#331111", fg="#FF8888",
                  command=self._reset).pack(pady=6)

    def _reset(self):
        for attr in ("reverb", "bass_db", "treble_db", "fade_in_s", "fade_out_s", "offset_s"):
            setattr(self.t, attr, 0.0)
        self.destroy()
        FXPanel(self.master, self.track_row)


# ── App principal ─────────────────────────────────────────────────────────

class AudioditApp:
    def __init__(self, root):
        self.root  = root
        self.root.title("audiodit")
        self.root.configure(bg="#121220")
        self.tracks: list[Track]    = []
        self.rows:   list[TrackRow] = []
        self._play_thread = None
        self._playing     = False
        self._recording   = False
        self._pressed_keys: set = set()

        self.synth    = PianoSynth() if HAS_SD else None
        self.recorder = Recorder()   if HAS_SD else None

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        # Toolbar
        tb = tk.Frame(self.root, bg="#1A1A2E", pady=4)
        tb.pack(side=tk.TOP, fill=tk.X)

        def tbtn(text, cmd, color="#333355"):
            return tk.Button(tb, text=text, command=cmd, bg=color, fg="#EEEEFF",
                             font=("Courier", 10, "bold"), relief=tk.FLAT,
                             padx=8, pady=2)

        tbtn("+ Pista",   self.add_track).pack(side=tk.LEFT, padx=4)
        self.play_btn = tbtn("▶ Play", self.toggle_play, "#1A4A1A")
        self.play_btn.pack(side=tk.LEFT, padx=2)
        tbtn("■ Stop",    self.stop_play, "#4A1A1A").pack(side=tk.LEFT, padx=2)
        tbtn("Exportar",  self.export,    "#2A2A4A").pack(side=tk.LEFT, padx=8)
        self.rec_btn = tbtn("● REC", self._toggle_rec, "#4A0000")
        self.rec_btn.pack(side=tk.LEFT, padx=4)

        tk.Label(tb, text="audiodit", bg="#1A1A2E", fg="#334466",
                 font=("Courier", 10)).pack(side=tk.RIGHT, padx=10)

        # Tracks area (scrollable)
        outer = tk.Frame(self.root, bg="#121220")
        outer.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.v_scroll = tk.Scrollbar(outer, orient=tk.VERTICAL, bg="#1A1A2E")
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.track_canvas = tk.Canvas(outer, bg="#121220", yscrollcommand=self.v_scroll.set,
                                       highlightthickness=0)
        self.track_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.v_scroll.config(command=self.track_canvas.yview)

        self.tracks_frame = tk.Frame(self.track_canvas, bg="#121220")
        self.tc_window = self.track_canvas.create_window((0, 0), window=self.tracks_frame,
                                                          anchor="nw")
        self.tracks_frame.bind("<Configure>", self._on_tracks_resize)
        self.track_canvas.bind("<Configure>", self._on_canvas_resize)

        # Empty state label
        self.empty_lbl = tk.Label(self.tracks_frame, text="+ Pista para agregar audio",
                                   bg="#121220", fg="#334455",
                                   font=("Courier", 14))
        self.empty_lbl.pack(pady=60)

        # Piano keyboard
        self._build_piano()

        # Status
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(self.root, textvariable=self.status_var, bg="#0D0D1A", fg="#556677",
                 font=("Courier", 9), anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

    # ── Piano ─────────────────────────────────────────────────────────────

    def _build_piano(self):
        piano_w = PIANO_PAD * 2 + len(WHITE_KEYS) * WKW
        piano_frame = tk.Frame(self.root, bg="#111118", pady=4)
        piano_frame.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Label(piano_frame, text="PIANO  (asdfghjkl = blancas | wetuyop = negras)",
                 bg="#111118", fg="#334455", font=("Courier", 8)).pack()

        self.piano_canvas = tk.Canvas(piano_frame, width=piano_w, height=WKH + 10,
                                       bg="#111118", highlightthickness=0)
        self.piano_canvas.pack()
        self._draw_piano_keys()

        # Bindings teclado
        self.root.bind("<KeyPress>",   self._piano_key_down)
        self.root.bind("<KeyRelease>", self._piano_key_up)
        # Click en canvas
        self.piano_canvas.bind("<ButtonPress-1>",   self._piano_click_down)
        self.piano_canvas.bind("<ButtonRelease-1>", self._piano_click_up)

    def _key_x(self, idx_float: float) -> int:
        return PIANO_PAD + int(idx_float * WKW)

    def _draw_piano_keys(self, pressed: set = None):
        pressed = pressed or set()
        c = self.piano_canvas
        c.delete("all")
        # Dibuja blancos primero, luego negros encima
        for idx, key, note, freq in WHITE_KEYS:
            x = self._key_x(idx)
            color = "#CCDDFF" if key in pressed else "#F4F0E8"
            c.create_rectangle(x, 4, x + WKW - 2, 4 + WKH,
                                fill=color, outline="#555566", width=1, tags=f"wk_{key}")
            # Nota en la tecla
            c.create_text(x + WKW//2, 4 + WKH - 22,
                          text=note[:2], fill="#333344", font=("Courier", 7))
            if key:
                c.create_text(x + WKW//2, 4 + WKH - 10,
                              text=key.upper(), fill="#666688", font=("Courier", 7, "bold"))

        for idx_f, key, note, freq in BLACK_KEYS:
            x = self._key_x(idx_f) - BKW // 2
            color = "#3344AA" if key in pressed else "#1A1A2A"
            c.create_rectangle(x, 4, x + BKW, 4 + BKH,
                                fill=color, outline="#444455", width=1, tags=f"bk_{key}")
            c.create_text(x + BKW//2, 4 + BKH - 14,
                          text=note[:3], fill="#8899CC", font=("Courier", 6))
            c.create_text(x + BKW//2, 4 + BKH - 5,
                          text=key.upper(), fill="#6677AA", font=("Courier", 6, "bold"))

    def _piano_key_down(self, event):
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)):
            return
        key = event.keysym.lower()
        if key in _ALL_KEYS and key not in self._pressed_keys:
            self._pressed_keys.add(key)
            freq = _ALL_KEYS[key][3]
            if self.synth: self.synth.note_on(freq)
            self._draw_piano_keys(self._pressed_keys)
            self.status_var.set(f"Nota: {_ALL_KEYS[key][2]}  ({freq:.1f} Hz)")

    def _piano_key_up(self, event):
        key = event.keysym.lower()
        if key in self._pressed_keys:
            self._pressed_keys.discard(key)
            freq = _ALL_KEYS[key][3]
            if self.synth: self.synth.note_off(freq)
            self._draw_piano_keys(self._pressed_keys)

    def _piano_canvas_key(self, cx, cy):
        # Revisar negras primero (encima visualmente)
        for idx_f, key, note, freq in BLACK_KEYS:
            x = self._key_x(idx_f) - BKW // 2
            if x <= cx <= x + BKW and 4 <= cy <= 4 + BKH:
                return key, freq
        # Luego blancas
        for idx, key, note, freq in WHITE_KEYS:
            x = self._key_x(idx)
            if x <= cx <= x + WKW - 2 and 4 <= cy <= 4 + WKH:
                return key, freq
        return None, None

    def _piano_click_down(self, event):
        key, freq = self._piano_canvas_key(event.x, event.y)
        if key and freq:
            self._pressed_keys.add(key)
            if self.synth: self.synth.note_on(freq)
            self._draw_piano_keys(self._pressed_keys)

    def _piano_click_up(self, event):
        for k in list(self._pressed_keys):
            if self.synth: self.synth.note_off(_ALL_KEYS[k][3])
        self._pressed_keys.clear()
        self._draw_piano_keys()

    # ── REC ───────────────────────────────────────────────────────────────

    def _toggle_rec(self):
        if not self.recorder:
            messagebox.showwarning("Sin audio", "sounddevice no disponible")
            return
        if self._recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _start_rec(self):
        self._recording = True
        self.rec_btn.config(text="■ STOP REC", bg="#AA0000")
        self.status_var.set("Grabando... (click STOP REC para terminar)")
        self.recorder.start()

    def _stop_rec(self):
        self._recording = False
        self.rec_btn.config(text="● REC", bg="#4A0000")
        path = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV", "*.wav"), ("Todos", "*.*")],
            title="Guardar grabacion")
        if path:
            ok = self.recorder.save(path)
            if ok:
                self.status_var.set(f"Grabacion guardada -> {path}")
                if messagebox.askyesno("Agregar pista", "Agregar grabacion como nueva pista?"):
                    self.add_track(path)
            else:
                self.status_var.set("Grabacion vacia")
        else:
            self.recorder.stop()
            self.status_var.set("Grabacion descartada")

    def _on_close(self):
        if self.synth: self.synth.close()
        self.root.destroy()

    def _on_tracks_resize(self, e):
        self.track_canvas.configure(scrollregion=self.track_canvas.bbox("all"))

    def _on_canvas_resize(self, e):
        self.track_canvas.itemconfig(self.tc_window, width=e.width)

    # ── Tracks ────────────────────────────────────────────────────────────

    def add_track(self, path=None):
        if not path:
            path = filedialog.askopenfilename(
                title="Agregar pista",
                filetypes=[("Audio", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac"),
                           ("Todos", "*.*")])
        if not path: return
        path = Path(path)
        self.status_var.set(f"Cargando {path.name}...")
        self.root.update()
        try:
            audio = AudioSegment.from_file(str(path))
            track = Track(name=path.stem, path=path, audio=audio)
            self.tracks.append(track)
            if hasattr(self, "empty_lbl") and self.empty_lbl.winfo_exists():
                self.empty_lbl.destroy()
            row = TrackRow(self.tracks_frame, track, self)
            row.pack(fill=tk.X, pady=1)
            self.rows.append(row)
            dur = len(audio) / 1000
            self.status_var.set(f"Cargado: {path.name}  ({int(dur//60)}:{int(dur%60):02d})")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status_var.set("Error al cargar")

    def remove_track(self, row: TrackRow):
        if row.track in self.tracks: self.tracks.remove(row.track)
        if row in self.rows:         self.rows.remove(row)
        row.destroy()
        if not self.tracks:
            self.empty_lbl = tk.Label(self.tracks_frame, text="+ Pista para agregar audio",
                                       bg="#121220", fg="#334455", font=("Courier", 14))
            self.empty_lbl.pack(pady=60)
        self.status_var.set("Pista eliminada")

    def open_fx_panel(self, row: TrackRow):
        FXPanel(self.root, row)

    # ── Playback ──────────────────────────────────────────────────────────

    def toggle_play(self):
        if self._playing:
            self.stop_play()
        else:
            self._start_play()

    def _start_play(self):
        if not self.tracks:
            messagebox.showinfo("Sin pistas", "Agrega al menos una pista primero")
            return
        self._playing = True
        self.play_btn.config(text="⏸ Pause", bg="#4A2A00")
        self.status_var.set("Mezclando...")
        self.root.update()

        def run():
            try:
                mix = _build_mix(self.tracks)
                if mix is None:
                    self.root.after(0, lambda: self.status_var.set("Todas las pistas en mute"))
                    self._playing = False
                    return

                if HAS_SD:
                    import numpy as np
                    samples = np.array(mix.get_array_of_samples(), dtype=np.float32)
                    if mix.channels == 2:
                        samples = samples.reshape(-1, 2)
                    samples /= 2**15
                    self.root.after(0, lambda: self.status_var.set(
                        f"Reproduciendo... ({len(mix)/1000:.1f}s)"))
                    sd.play(samples, mix.frame_rate)
                    sd.wait()
                else:
                    import tempfile, os
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                        tmp = tf.name
                    mix.export(tmp, format="wav")
                    os.startfile(tmp)
                    self.root.after(0, lambda: self.status_var.set("Reproduciendo en player externo"))

            except Exception as ex:
                self.root.after(0, lambda: messagebox.showerror("Error playback", str(ex)))
            finally:
                self._playing = False
                self.root.after(0, lambda: self.play_btn.config(text="▶ Play", bg="#1A4A1A"))
                self.root.after(0, lambda: self.status_var.set("Listo"))

        self._play_thread = threading.Thread(target=run, daemon=True)
        self._play_thread.start()

    def stop_play(self):
        if HAS_SD:
            sd.stop()
        self._playing = False
        self.play_btn.config(text="▶ Play", bg="#1A4A1A")
        self.status_var.set("Detenido")

    # ── Export ────────────────────────────────────────────────────────────

    def export(self):
        if not self.tracks:
            messagebox.showinfo("Sin pistas", "Agrega pistas primero")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            filetypes=[("MP3", "*.mp3"), ("WAV", "*.wav"), ("OGG", "*.ogg"), ("FLAC", "*.flac")])
        if not path: return

        # Options dialog
        dlg = tk.Toplevel(self.root)
        dlg.title("Exportar")
        dlg.configure(bg="#1A1A2E")
        dlg.grab_set()

        tk.Label(dlg, text="Bitrate (kbps):", bg="#1A1A2E", fg="#AAAACC").grid(row=0, column=0, padx=8, pady=4)
        br_var = tk.IntVar(value=192)
        tk.Spinbox(dlg, from_=64, to=320, increment=32, textvariable=br_var,
                   width=6, bg="#111122", fg="#CCCCFF").grid(row=0, column=1)

        norm_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Normalizar", variable=norm_var,
                       bg="#1A1A2E", fg="#AAAACC", selectcolor="#003300").grid(
            row=1, column=0, columnspan=2, pady=4)

        def do_export():
            dlg.destroy()
            self.status_var.set("Exportando...")
            self.root.update()
            try:
                mix = _build_mix(self.tracks)
                if mix is None:
                    messagebox.showwarning("Sin audio", "Todas las pistas en mute")
                    return
                if norm_var.get():
                    mix = pydub_normalize(mix)
                fmt = Path(path).suffix.lstrip(".")
                kw = {"bitrate": f"{br_var.get()}k"} if fmt in ("mp3", "ogg") else {}
                mix.export(path, format=fmt, **kw)
                self.status_var.set(f"Exportado -> {path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))
                self.status_var.set("Error al exportar")

        tk.Button(dlg, text="Exportar", command=do_export,
                  bg="#1A4A1A", fg="#AAFFAA").grid(row=2, column=0, columnspan=2, pady=8)
        dlg.wait_window()


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.geometry("1000x600")
    root.minsize(700, 400)
    app = AudioditApp(root)
    if len(sys.argv) > 1:
        root.after(200, lambda: app.add_track(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
