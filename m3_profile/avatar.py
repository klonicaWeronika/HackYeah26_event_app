"""
M3 — przetwarzanie zdjęcia profilowego (czysta logika, BEZ streamlit -> testowalna pytestem).

    avatar_from_upload(data: bytes) -> str     # "data:image/jpeg;base64,..." do User.avatar_url

Kroki: limit rozmiaru pliku -> dekodowanie (Pillow) -> obrót wg EXIF (zdjęcia z telefonu)
-> przezroczystość na białe tło -> środkowy kadr do kwadratu 256×256 -> JPEG q80 bez EXIF
(q70/q60, gdy data URI wyszłoby > 60 KB). Każdy błąd = AvatarError z polskim komunikatem dla UI.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 5 * 1024 * 1024          # 5 MB — limit pliku od użytkownika
MAX_SOURCE_PIXELS = 50_000_000              # ochrona przed „bombą dekompresyjną” (mały plik, gigantyczny obraz)
AVATAR_SIZE = 256                           # px, kwadrat
MAX_DATA_URI_BYTES = 60_000                 # cel: awatar trafia do HTML przy każdym renderze
JPEG_QUALITIES = (80, 70, 60)               # kolejne próby, gdy wynik jest za duży
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}   # MPO = JPEG z niektórych telefonów/aparatów
DATA_URI_PREFIX = "data:image/jpeg;base64,"
_TOO_MANY_PIXELS = "Zdjęcie ma zbyt dużą rozdzielczość — wybierz mniejsze (do 50 Mpx)."


class AvatarError(ValueError):
    """Nie da się zrobić awatara z pliku. `str(exc)` to gotowy komunikat PL do `st.error`."""


def avatar_from_upload(data: bytes) -> str:
    """Bajty JPG/PNG/WEBP -> data URI kwadratowego JPEG-a 256×256 (< 60 KB). Rzuca AvatarError."""
    if not data:
        raise AvatarError("Plik jest pusty — wybierz zdjęcie JPG, PNG albo WEBP.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise AvatarError(
            f"Zdjęcie jest za duże ({len(data) / 1024 / 1024:.1f} MB). Maksymalny rozmiar to 5 MB."
        )
    try:
        square = _to_square_rgb(data)
        return _encode_data_uri(square)
    except AvatarError:
        raise
    except Image.DecompressionBombError as exc:          # Pillow: > 2× MAX_IMAGE_PIXELS już przy otwarciu
        raise AvatarError(_TOO_MANY_PIXELS) from exc
    except Exception as exc:  # Pillow na uszkodzonym pliku rzuca różnymi wyjątkami (OSError, SyntaxError, …)
        raise AvatarError(
            "Nie udało się odczytać zdjęcia — plik jest uszkodzony albo to nie jest obraz. "
            "Spróbuj innego pliku JPG, PNG lub WEBP."
        ) from exc


def _to_square_rgb(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as img:
        if img.format not in ALLOWED_FORMATS:
            raise AvatarError("Nieobsługiwany format pliku — wybierz zdjęcie JPG, PNG albo WEBP.")
        if img.width * img.height > MAX_SOURCE_PIXELS:
            raise AvatarError(_TOO_MANY_PIXELS)
        if img.format in {"JPEG", "MPO"}:
            img.draft("RGB", (AVATAR_SIZE * 2, AVATAR_SIZE * 2))   # szybkie dekodowanie w niższej skali
        img.load()
        try:
            img = ImageOps.exif_transpose(img)                     # pion/poziom jak w telefonie
        except Exception:                                          # uszkodzone EXIF nie blokuje zdjęcia
            pass
        img = _flatten_on_white(img)
    return ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _flatten_on_white(img: Image.Image) -> Image.Image:
    """RGBA/LA/P z przezroczystością -> RGB na białym tle (JPEG nie ma kanału alfa)."""
    has_alpha = img.mode in {"RGBA", "LA", "PA", "RGBa", "La"} or (
        img.mode == "P" and "transparency" in img.info
    )
    if not has_alpha:
        return img.convert("RGB")
    rgba = img.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _encode_data_uri(img: Image.Image) -> str:
    uri = ""
    for quality in JPEG_QUALITIES:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)   # bez exif=… -> brak metadanych
        uri = DATA_URI_PREFIX + base64.b64encode(buf.getvalue()).decode("ascii")
        if len(uri) <= MAX_DATA_URI_BYTES:
            break
    return uri
