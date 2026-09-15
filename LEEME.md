<p align="center">
  <a href="README.md">English</a> · <b>Español</b>
</p>

<div align="center">

<img src="recursos/devtools.svg" width="104" alt="DevTools">

# DevTools

### Dos herramientas de taller: una de audio, otra de pixel art.

`audiodit` corta, mezcla y procesa sonido desde la terminal — y convierte un
tarareo en notas. `pixedit` vuelve un sprite **texto plano que puedes diffear en
git**, y de regreso.

[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-2c7a51?style=flat-square)](LICENSE)
[![Python 3](https://img.shields.io/badge/python-3-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
![CLI + GUI](https://img.shields.io/badge/interfaz-CLI%20%2B%20GUI-e9a13b?style=flat-square)
![Plataforma](https://img.shields.io/badge/plataforma-Windows%20·%20Linux%20·%20macOS-777?style=flat-square)

</div>

---

## Qué es

Dos herramientas que no tienen nada que ver entre sí, salvo que las necesitó la
misma persona la misma tarde y comparten carpeta. Las dos funcionan igual: una
**interfaz por línea de comandos** para hacer el trabajo, y una **interfaz
gráfica** opcional para cuando prefieres ver lo que estás haciendo.

Se instalan por separado. Si sólo quieres la de sprites, nunca necesitas ffmpeg.

## Propósito y alcance

**El propósito.** Herramientas chicas y filosas para trabajos que normalmente
implican abrir algo enorme. Recortarle treinta segundos a un MP3 no debería
requerir levantar un DAW, y versionar un sprite de 16×16 no debería significar
subir un binario opaco cada vez que mueves un píxel.

**Qué abarca.** Ediciones de audio del día a día desde un script o una terminal,
y un formato de texto de ida y vuelta para pixel art chico.

**Qué no hace.** Ninguna de las dos pretende reemplazar a Audacity ni a Aseprite.
No hay línea de tiempo, ni capas, ni animación — a propósito.

## Contenido

- [audiodit — audio desde la terminal](#audiodit--audio-desde-la-terminal)
- [pixedit — pixel art como texto](#pixedit--pixel-art-como-texto)
- [En Windows](#en-windows)
- [Para quien quiera meter mano](#contribuir)

## audiodit — audio desde la terminal

```bash
pip install pydub numpy librosa      # más ffmpeg en el PATH
python audiodit.py --help
```

| comando | qué hace |
|---|---|
| `audiodit info cancion.mp3` | Duración, formato, canales, bitrate. |
| `audiodit cut cancion.mp3 0:30 1:45 fragmento.mp3` | Recorta por tiempo, no por número de muestra. |
| `audiodit concat intro.mp3 loop.mp3 outro.mp3 -o final.mp3` | Pega archivos uno tras otro. |
| `audiodit overlay voz.wav musica.mp3 -o mezcla.mp3` | Encima uno de otro. `--offsets 0 4.5` arranca el segundo tarde. |
| `audiodit volume track.mp3 +6 louder.mp3` | Ganancia en dB, con signo. |
| `audiodit speed track.mp3 1.5 rapido.mp3` | Acelera o frena. |
| `audiodit fade track.mp3 suave.mp3 --in 2 --out 3` | Entrada y salida, en segundos. |
| `audiodit normalize track.mp3 norm.mp3` | Empareja el nivel. |
| `audiodit bitrate track.mp3 128 comprimido.mp3` | Recodifica más chico. |
| `audiodit effects track.mp3 fx.mp3 --reverb 0.4 --bass 4` | Reverberación y ecualización. |
| `audiodit hum2notes tarareada.wav --midi` | **Tarareas una melodía y te da las notas.** Le sigue el tono a la grabación y escribe lo que cantaste, opcionalmente como MIDI. |
| `audiodit gui` | La ventana, para lo mismo. |

`hum2notes` es el que vale la pena conocer: es la diferencia entre «traigo una
tonada en la cabeza» y «tengo un archivo MIDI», sin tocar un instrumento.

## pixedit — pixel art como texto

```bash
pip install pillow
python pixedit.py --help
```

Lo bueno de ésta es el formato. Un `.px` es una paleta más una rejilla de
índices: **se lee, se edita y se diffea**.

```
size: 16x16
palette:
  0: #00000000
  1: #FF5000
  2: #000000
  3: #B40000
pixels:
0000000000000000
0000111111110000
0000111111110000
0000112112110000
0000111111110000
0000111111110000
0000113333110000
0000111111110000
0000000000000000
```

<p align="center">
<img src="docs/imagenes/sprite-ejemplo.png" width="220" alt="El sprite que describe ese texto, ampliado 16×">
</p>

Ése es el `test_sprite.px` que viene en este repositorio, y la imagen de al lado
es lo que `pixedit decode` hace con él. Mueve un píxel y `git diff` te enseña un
carácter cambiando — en vez de *«Binary files differ»*.

| comando | qué hace |
|---|---|
| `pixedit encode sprite.png` | PNG → `.px` |
| `pixedit decode sprite.px` | `.px` → PNG |
| `pixedit preview sprite.png [escala]` | Ventana con el sprite ampliado (×8 por omisión). |
| `pixedit scale sprite.png 4` | Escala por vecino más cercano — sin desenfocar. |
| `pixedit info sprite.png` | Dimensiones y cuántos colores. |
| `pixedit palette sprite.png` | Lista la paleta. |
| `pixedit gui [archivo]` | El editor. |

## En Windows

Los `.cmd` son envoltorios: pon la carpeta en el `PATH` y puedes llamar
`audiodit ...` y `pixedit ...` directo, sin escribir `python`.

<br>

---

<div align="center">

## 🔧 Para quien quiera meter mano

*Todo lo de arriba es lo que hacen. Todo lo de abajo es cómo lo hacen.*

</div>

---

### Contribuir

Cosas concretas que ayudarían:

- **Animación en el formato `.px`** — bastaría un separador de cuadros, y
  conservaría la propiedad de ser diffeable, que es lo que hace que el formato
  valga la pena.
- **`audiodit` sin ffmpeg** para las operaciones simples, para que la instalación
  deje de ser en dos pasos.
- **Pruebas de ida y vuelta.** `encode` → `decode` → `encode` debería ser un punto
  fijo, y ahorita nada lo garantiza. `test_roundtrip.png` existe justamente
  porque eso se comprobó a mano una vez.

### De qué está hecho

| la parte difícil | quién la hace |
|---|---|
| Decodificar y recodificar lo que sea (mp3, wav, ogg…) | `pydub`, y ffmpeg por debajo |
| Sacar qué nota es un tarareo | el seguimiento de tono de `librosa` |
| Cuentas sobre las muestras | `numpy` |
| Leer y escribir PNG, y la paleta | `pillow` |
| Las dos ventanas | Tkinter, de la librería estándar |

Las dos herramientas **no comparten nada**, ni siquiera dependencias. Es a
propósito: `pixedit` sirve en una máquina sin ffmpeg, y ponerles una base común
habría costado eso.

### Los archivos

| archivo | líneas | qué es |
|---|--:|---|
| `audiodit.py` | 276 | La CLI de audio. |
| `audiodit_gui.py` | 676 | Su ventana. |
| `pixedit.py` | 198 | La CLI de sprites, y el lector-escritor del `.px`. |
| `pixedit_gui.py` | 646 | El editor de sprites. |
| `test_sprite.px` / `test_sprite.png` | — | El mismo sprite de 16×16 en los dos formatos — el ejemplo que usa este LEEME. |
| `test_sprite_x4.png` | — | La salida de `pixedit scale test_sprite.png 4`. |

En los dos casos la ventana es tres veces más grande que la herramienta que
envuelve, y está bien así: la lógica es chica y el trabajo se va en los píxeles.

### Cómo funciona el formato `.px`

Tres secciones, en orden: `size:` con las dimensiones, `palette:` mapeando un
carácter a un color `#RRGGBBAA`, y `pixels:` con un renglón por fila.

Ese diseño tiene una consecuencia que conviene decir: **un sprite queda limitado
a tantos colores como caracteres de índice haya**. Para pixel art eso es una
virtud más que un tope —una paleta corta es de lo que está hecho el estilo— pero
significa que el formato nunca va a servir para una fotografía, y no pretende
hacerlo.

La transparencia vive en la paleta, no en un canal aparte: `#00000000` es la
entrada transparente. Por eso el índice `0` es el fondo en el ejemplo de arriba.

### Licencia

[MIT](LICENSE). Haz lo que quieras con ellas.

### Proyectos relacionados

- **[Aseprite](https://www.aseprite.org/)** — *ése para dibujar de verdad;*
  `pixedit` para meter el resultado al control de versiones de una forma que
  puedas leer.
- **[Audacity](https://www.audacityteam.org/)** — *ése cuando necesitas ver la
  onda.* `audiodit` es para cuando ya sabes qué quieres y prefieres teclearlo.
- **ffmpeg** — el que hace el trabajo de verdad debajo de `audiodit`. Si te
  llevas bien con su sintaxis, a lo mejor no necesitas esto.
