# DevTools

Dos herramientas de línea de comandos (con GUI opcional) para editar audio e imágenes pixel-art desde la terminal.

## audiodit — edición de audio

Cortar, mezclar, aplicar efectos, cambiar bitrate y convertir un tarareo en notas.

```
python audiodit.py --help
```

Requisitos:
```
pip install pydub numpy librosa
```
Además necesitas **ffmpeg** en el PATH.

GUI: `python audiodit_gui.py`

## pixedit — pixel art como texto

Convierte imágenes a un formato de texto `.px` (paleta + grilla de índices) y de regreso. Sirve para versionar sprites en git como texto plano. Comandos: `encode`, `decode`, `preview`, `scale`, `info`.

```
python pixedit.py --help
```

Requisitos:
```
pip install pillow
```

GUI: `python pixedit_gui.py`

Hay archivos `test_sprite.*` de ejemplo del formato `.px`.

## Windows

Los `.cmd` son envoltorios: puedes llamar `audiodit ...` y `pixedit ...` directo si la carpeta está en el PATH.
