#!/usr/bin/env python3
"""
audiodit — edicion de audio CLI
Corta, mezcla, efectos, bitrate, hum->notas
Requiere: pydub, numpy, librosa (para hum2notes), ffmpeg en PATH
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import warnings
warnings.filterwarnings("ignore")

try:
    from pydub import AudioSegment
    from pydub.effects import normalize as pydub_normalize
except ImportError:
    sys.exit("pip install pydub  (y ffmpeg en PATH)")

import numpy as np


# ── Utilidades ────────────────────────────────────────────────────────────

def parse_time(s: str) -> float:
    """'30' | '1:30' | '1:30.5'  ->  segundos"""
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) * 60 + float(sec)
    return float(s)

def fmt_time(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"

def load(path) -> AudioSegment:
    return AudioSegment.from_file(str(path))

def save(audio: AudioSegment, path, bitrate="192k"):
    path = Path(path)
    fmt = path.suffix.lstrip(".") or "mp3"
    kw = {"bitrate": bitrate} if fmt in ("mp3", "ogg") else {}
    audio.export(str(path), format=fmt, **kw)

def _reverb(audio: AudioSegment, size=0.3) -> AudioSegment:
    delay = max(15, int(size * 120))
    result = audio
    for i in range(1, 5):
        pad = AudioSegment.silent(duration=delay * i)
        ghost = (pad + audio) - (4 * i)
        result = result.overlay(ghost[:len(result)])
    return result

def _eq(audio: AudioSegment, bass_db=0.0, treble_db=0.0) -> AudioSegment:
    try:
        from pydub.scipy_effects import low_pass_filter, high_pass_filter
    except ImportError:
        return audio  # scipy no disponible

    result = audio
    if bass_db:
        low = low_pass_filter(audio, 300) + bass_db
        result = result.overlay(low)
    if treble_db:
        high = high_pass_filter(audio, 4000) + treble_db
        result = result.overlay(high)
    return result


# ── Comandos ──────────────────────────────────────────────────────────────

def cmd_info(args):
    a = load(args.file)
    dur = len(a) / 1000
    print(f"Archivo     : {args.file}")
    print(f"Duracion    : {fmt_time(dur)} ({dur:.2f}s)")
    print(f"Canales     : {a.channels} ({'stereo' if a.channels == 2 else 'mono'})")
    print(f"Sample rate : {a.frame_rate} Hz")
    print(f"Bit depth   : {a.sample_width * 8} bits")
    print(f"Bitrate apr.: ~{a.frame_rate * a.sample_width * 8 * a.channels // 1000} kbps")


def cmd_cut(args):
    a = load(args.file)
    s = int(parse_time(args.start) * 1000)
    e = int(parse_time(args.end) * 1000) if args.end else len(a)
    cut = a[s:e]
    save(cut, args.output)
    print(f"OK  {fmt_time(s/1000)}-{fmt_time(e/1000)}  ({len(cut)/1000:.2f}s)  ->  {args.output}")


def cmd_concat(args):
    result = AudioSegment.empty()
    for f in args.files:
        result += load(f)
    save(result, args.output)
    print(f"OK  {len(args.files)} archivos  ({len(result)/1000:.2f}s)  ->  {args.output}")


def cmd_overlay(args):
    tracks = [load(f) for f in args.files]
    # Normalizar duracion al mas largo
    max_dur = max(len(t) for t in tracks)
    result = AudioSegment.silent(duration=max_dur)
    for i, t in enumerate(tracks):
        offset_ms = int(parse_time(args.offsets[i]) * 1000) if args.offsets and i < len(args.offsets) else 0
        result = result.overlay(t, position=offset_ms)
    if args.normalize:
        result = pydub_normalize(result)
    save(result, args.output)
    print(f"OK  {len(tracks)} pistas mezcladas  ->  {args.output}")


def cmd_volume(args):
    a = load(args.file) + args.db
    save(a, args.output)
    print(f"OK  {args.db:+.1f} dB  ->  {args.output}")


def cmd_speed(args):
    a = load(args.file)
    new_rate = int(a.frame_rate * args.factor)
    fast = a._spawn(a.raw_data, overrides={"frame_rate": new_rate}).set_frame_rate(a.frame_rate)
    save(fast, args.output)
    print(f"OK  x{args.factor}  ({len(fast)/1000:.2f}s)  ->  {args.output}")


def cmd_fade(args):
    a = load(args.file)
    if args.fade_in  > 0: a = a.fade_in(int(args.fade_in  * 1000))
    if args.fade_out > 0: a = a.fade_out(int(args.fade_out * 1000))
    save(a, args.output)
    print(f"OK  in={args.fade_in}s out={args.fade_out}s  ->  {args.output}")


def cmd_bitrate(args):
    a = load(args.file)
    save(a, args.output, bitrate=f"{args.kbps}k")
    print(f"OK  {args.kbps} kbps  ->  {args.output}")


def cmd_normalize(args):
    save(pydub_normalize(load(args.file)), args.output)
    print(f"OK  normalizado  ->  {args.output}")


def cmd_effects(args):
    a = load(args.file)
    if args.reverb:  a = _reverb(a, args.reverb)
    if args.bass or args.treble: a = _eq(a, args.bass, args.treble)
    if args.normalize: a = pydub_normalize(a)
    save(a, args.output)
    applied = []
    if args.reverb:    applied.append(f"reverb={args.reverb}")
    if args.bass:      applied.append(f"bass={args.bass:+.1f}dB")
    if args.treble:    applied.append(f"treble={args.treble:+.1f}dB")
    if args.normalize: applied.append("normalize")
    print(f"OK  {', '.join(applied) or 'sin efectos'}  ->  {args.output}")


def cmd_hum2notes(args):
    try:
        import librosa
    except ImportError:
        sys.exit("pip install librosa")

    print(f"Analizando {args.file}...")
    y, sr = librosa.load(str(args.file), sr=None, mono=True)

    f0, voiced, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sr,
    )
    times = librosa.times_like(f0, sr=sr)

    vt = times[voiced]
    vf = f0[voiced]
    if len(vf) == 0:
        sys.exit("No se detectaron notas. Prueba con audio mas limpio.")

    raw_notes = librosa.hz_to_note(vf)

    # Agrupar notas consecutivas iguales
    segments = []
    prev, t0 = None, None
    for t, note in zip(vt, raw_notes):
        if note != prev:
            if prev: segments.append((t0, t - t0, prev))
            prev, t0 = note, t
    if prev: segments.append((t0, vt[-1] - t0, prev))

    # -- Texto --
    lines = [f"# Notas de: {args.file}", f"# {len(segments)} notas\n",
             f"{'Inicio':>8}  {'Nota':<5}  {'Dur':>6}  Intensidad"]
    for start, dur, note in segments:
        bar = "=" * min(30, int(dur * 15))
        lines.append(f"{fmt_time(start):>8}  {note:<5}  {dur:5.2f}s  {bar}")

    txt = "\n".join(lines)
    out_txt = args.output or Path(args.file).with_suffix(".txt")
    Path(out_txt).write_text(txt, encoding="utf-8")
    print(txt)
    print(f"\nGuardado -> {out_txt}")

    # -- MIDI opcional --
    if args.midi:
        try:
            from midiutil import MIDIFile
        except ImportError:
            print("Para MIDI: pip install MIDIUtil")
            return

        midi = MIDIFile(1)
        midi.addTempo(0, 0, 120)
        beat = 60 / 120  # segundos por beat a 120 BPM

        for start, dur, note in segments:
            try:
                pitch = librosa.note_to_midi(note)
                midi.addNote(0, 0, pitch, start / beat, max(0.1, dur / beat), 90)
            except Exception:
                pass

        mid_path = Path(out_txt).with_suffix(".mid")
        with open(mid_path, "wb") as f:
            midi.writeFile(f)
        print(f"MIDI -> {mid_path}")


def cmd_gui(args):
    gui = Path(__file__).parent / "audiodit_gui.py"
    if not gui.exists():
        sys.exit(f"No encuentro audiodit_gui.py en {gui.parent}")
    cmd = [sys.executable, str(gui)]
    if args.file: cmd.append(str(args.file))
    subprocess.Popen(cmd)
    print("GUI abierta")


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="audiodit — edicion de audio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ejemplos:
  audiodit info cancion.mp3
  audiodit cut  cancion.mp3 0:30 1:45 fragmento.mp3
  audiodit overlay voz.wav musica.mp3 -o mezcla.mp3
  audiodit overlay a.mp3 b.mp3 --offsets 0 4.5 -o mezcla.mp3
  audiodit concat intro.mp3 loop.mp3 outro.mp3 -o final.mp3
  audiodit volume track.mp3 +6 louder.mp3
  audiodit speed  track.mp3 1.5 rapido.mp3
  audiodit fade   track.mp3 suave.mp3 --in 2 --out 3
  audiodit bitrate track.mp3 128 comprimido.mp3
  audiodit normalize track.mp3 norm.mp3
  audiodit effects track.mp3 fx.mp3 --reverb 0.4 --bass 4
  audiodit hum2notes tarareada.wav --midi
  audiodit gui
        """,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def sp(name, help_):
        return sub.add_parser(name, help=help_)

    s = sp("info", "info del archivo")
    s.add_argument("file")

    s = sp("cut", "cortar segmento")
    s.add_argument("file")
    s.add_argument("start", help="tiempo inicio  ej: 30  o  1:30")
    s.add_argument("end",   help="tiempo fin     ej: 1:45  (omitir = hasta el final)", nargs="?")
    s.add_argument("output")

    s = sp("concat", "concatenar archivos en orden")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output", required=True)

    s = sp("overlay", "superponer/mezclar pistas")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--offsets", nargs="+", default=[], metavar="SEG",
                   help="offset en segundos para cada pista")
    s.add_argument("--normalize", action="store_true")

    s = sp("volume", "ajustar volumen en dB")
    s.add_argument("file")
    s.add_argument("db", type=float, help="dB  ej: +6  o  -3")
    s.add_argument("output")

    s = sp("speed", "cambiar velocidad (pitch se ve afectado)")
    s.add_argument("file")
    s.add_argument("factor", type=float, help="ej: 1.5 = 50%% mas rapido")
    s.add_argument("output")

    s = sp("fade", "fade in / out")
    s.add_argument("file")
    s.add_argument("output")
    s.add_argument("--in",  dest="fade_in",  type=float, default=0, metavar="SEG")
    s.add_argument("--out", dest="fade_out", type=float, default=0, metavar="SEG")

    s = sp("bitrate", "cambiar bitrate (MP3/OGG)")
    s.add_argument("file")
    s.add_argument("kbps", type=int, help="ej: 128  192  320")
    s.add_argument("output")

    s = sp("normalize", "normalizar volumen al maximo sin clipear")
    s.add_argument("file")
    s.add_argument("output")

    s = sp("effects", "aplicar efectos")
    s.add_argument("file")
    s.add_argument("output")
    s.add_argument("--reverb",    type=float, default=0,   metavar="0-1")
    s.add_argument("--bass",      type=float, default=0,   metavar="DB")
    s.add_argument("--treble",    type=float, default=0,   metavar="DB")
    s.add_argument("--normalize", action="store_true")

    s = sp("hum2notes", "detectar notas en una tarareada")
    s.add_argument("file", help="archivo de audio (.wav recomendado)")
    s.add_argument("output", nargs="?", help="archivo .txt (default: mismo nombre)")
    s.add_argument("--midi", action="store_true", help="generar .mid tambien")

    s = sp("gui", "abrir editor grafico")
    s.add_argument("file", nargs="?", help="archivo para abrir al iniciar")

    args = p.parse_args()
    {
        "info": cmd_info, "cut": cmd_cut, "concat": cmd_concat,
        "overlay": cmd_overlay, "volume": cmd_volume, "speed": cmd_speed,
        "fade": cmd_fade, "bitrate": cmd_bitrate, "normalize": cmd_normalize,
        "effects": cmd_effects, "hum2notes": cmd_hum2notes, "gui": cmd_gui,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
