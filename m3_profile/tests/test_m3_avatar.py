"""M3-02 — avatar_from_upload: zdjęcia generowane w pamięci (bez plików w repo)."""

from __future__ import annotations

import base64
import io
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
from PIL import Image

from m3_profile.avatar import (
    AVATAR_SIZE,
    DATA_URI_PREFIX,
    MAX_DATA_URI_BYTES,
    MAX_UPLOAD_BYTES,
    AvatarError,
    avatar_from_upload,
)

ROOT = Path(__file__).resolve().parents[2]
RED, BLUE, WHITE = (255, 0, 0), (0, 0, 255), (255, 255, 255)


# --------------------------------------------------------------------------- #
# Pomocnicze
# --------------------------------------------------------------------------- #

def _encode(img: Image.Image, fmt: str = "JPEG", **params) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **params)
    return buf.getvalue()


def _decode(uri: str) -> Image.Image:
    assert uri.startswith(DATA_URI_PREFIX)
    img = Image.open(io.BytesIO(base64.b64decode(uri[len(DATA_URI_PREFIX):])))
    img.load()
    return img


def _close(pixel, expected, tol: int = 40) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(pixel, expected))


def _halves(size: tuple[int, int], first, second, *, vertical_split: bool) -> Image.Image:
    """Obraz z dwiema połówkami: lewa/prawa (vertical_split) albo górna/dolna."""
    img = Image.new("RGB", size, second)
    w, h = size
    img.paste(first, (0, 0, w // 2, h) if vertical_split else (0, 0, w, h // 2))
    return img


# --------------------------------------------------------------------------- #
# Szczęśliwe ścieżki
# --------------------------------------------------------------------------- #

def test_portrait_photo_becomes_256_square_jpeg_under_limit():
    portrait = _halves((600, 1000), RED, BLUE, vertical_split=False)     # góra czerwona, dół niebieski
    uri = avatar_from_upload(_encode(portrait))
    out = _decode(uri)
    assert (out.format, out.mode, out.size) == ("JPEG", "RGB", (AVATAR_SIZE, AVATAR_SIZE))
    assert len(uri) < MAX_DATA_URI_BYTES
    # środkowy kadr: góra nadal czerwona, dół niebieski (nic nie zostało obrócone ani ściśnięte)
    assert _close(out.getpixel((128, 10)), RED) and _close(out.getpixel((128, 245)), BLUE)


def test_phone_photo_with_exif_orientation_is_rotated_upright():
    """Telefon zapisuje piksele „na boku” + EXIF Orientation=6 (obróć o 90° w prawo)."""
    stored = _halves((400, 200), RED, BLUE, vertical_split=True)        # zapisane: lewa czerwona, prawa niebieska
    exif = Image.Exif()
    exif[0x0112] = 6
    out = _decode(avatar_from_upload(_encode(stored, exif=exif.tobytes())))
    # po obrocie w prawo lewa strona staje się górą: cały górny wiersz czerwony, dolny niebieski
    for x in (10, 128, 245):
        assert _close(out.getpixel((x, 10)), RED), x
        assert _close(out.getpixel((x, 245)), BLUE), x


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_transparency_is_flattened_on_white(mode):
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))                   # przezroczyste „czarne” tło
    img.paste((20, 20, 20, 255), (100, 100, 200, 200))                  # nieprzezroczysty środek
    if mode == "LA":
        img = img.convert("LA")
    elif mode == "P":
        img = img.convert("P", palette=Image.Palette.ADAPTIVE)
        img.info["transparency"] = img.getpixel((0, 0))
    out = _decode(avatar_from_upload(_encode(img, "PNG")))
    assert _close(out.getpixel((5, 5)), WHITE, tol=10), "przezroczystość ma być biała, nie czarna"
    assert _close(out.getpixel((128, 128)), (20, 20, 20))


def test_webp_and_small_images_are_supported():
    out = _decode(avatar_from_upload(_encode(Image.new("RGB", (50, 80), BLUE), "WEBP")))
    assert out.size == (AVATAR_SIZE, AVATAR_SIZE) and _close(out.getpixel((128, 128)), BLUE)


def test_grayscale_and_cmyk_jpeg_are_converted_to_rgb():
    for img in (Image.new("L", (300, 300), 128), Image.new("CMYK", (300, 300), (0, 0, 0, 0))):
        assert _decode(avatar_from_upload(_encode(img))).mode == "RGB"


def test_output_has_no_exif_metadata():
    """Metadane z telefonu (model, GPS…) nie mogą trafić do bazy ani do HTML."""
    exif = Image.Exif()
    exif[0x010F] = "TelefonTestowy"      # Make
    exif[0x0112] = 1
    out = _decode(avatar_from_upload(_encode(Image.new("RGB", (400, 400), RED), exif=exif.tobytes())))
    assert len(out.getexif()) == 0 and "exif" not in out.info


def test_noisy_photo_still_fits_size_limit():
    """Najgorszy przypadek dla JPEG-a (szum) -> zejście z jakością do q70/q60 mieści się w 60 KB."""
    noise = Image.frombytes("RGB", (512, 512), os.urandom(512 * 512 * 3))
    uri = avatar_from_upload(_encode(noise, quality=95))
    assert len(uri) <= MAX_DATA_URI_BYTES


# --------------------------------------------------------------------------- #
# Błędy -> AvatarError z polskim komunikatem (UI pokazuje go przez st.error)
# --------------------------------------------------------------------------- #

def test_too_large_file_is_rejected_with_message():
    with pytest.raises(AvatarError, match="5 MB"):
        avatar_from_upload(b"\xff" * (MAX_UPLOAD_BYTES + 1))


@pytest.mark.parametrize("data", [
    b"",
    b"to nie jest obraz",
    _encode(Image.new("RGB", (400, 400), RED))[:300],                  # ucięty JPEG
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,                               # zepsuty nagłówek PNG
])
def test_corrupted_or_empty_file_is_rejected(data):
    with pytest.raises(AvatarError) as exc:
        avatar_from_upload(data)
    assert "zdjęci" in str(exc.value).lower() or "plik" in str(exc.value).lower()


@pytest.mark.parametrize("fmt", ["GIF", "BMP"])
def test_unsupported_format_is_rejected(fmt):
    with pytest.raises(AvatarError, match="format"):
        avatar_from_upload(_encode(Image.new("RGB", (100, 100), RED), fmt))


@pytest.mark.parametrize("width, height", [(8_000, 7_500), (20_000, 20_000)])   # nasz limit / limit Pillow
def test_decompression_bomb_is_rejected_before_decoding(width, height):
    """Mały plik deklarujący gigantyczną rozdzielczość nie może zjeść RAM-u serwera."""
    png = bytearray(_encode(Image.new("L", (10, 10)), "PNG"))
    ihdr = 8                                                            # sygnatura PNG(8), potem: długość(4) "IHDR"(4) dane(13) CRC(4)
    png[ihdr + 8:ihdr + 16] = struct.pack(">II", width, height)
    png[ihdr + 21:ihdr + 25] = struct.pack(">I", zlib.crc32(bytes(png[ihdr + 4:ihdr + 21])))
    with pytest.raises(AvatarError, match="rozdzielczo"):
        avatar_from_upload(bytes(png))


def test_avatar_error_is_a_value_error():
    assert issubclass(AvatarError, ValueError)


# --------------------------------------------------------------------------- #
# Kontrakt modułu
# --------------------------------------------------------------------------- #

def test_views_reexports_public_api():
    from m3_profile import views

    assert views.avatar_from_upload is avatar_from_upload and views.AvatarError is AvatarError


def test_avatar_module_does_not_import_streamlit():
    code = "import sys, m3_profile.avatar; sys.exit('streamlit' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=ROOT).returncode == 0
