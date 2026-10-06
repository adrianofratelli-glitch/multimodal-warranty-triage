"""Uploads hostis contra a normalização de imagem (sem Atlas, sem rede).

Cada caso reproduz um achado da revisão adversarial de 2026-10-06.
"""

import asyncio
import io
import struct
import zlib

import pytest
from PIL import Image
from starlette.datastructures import Headers, UploadFile

import config
from db import SafeQueryError
from main import _ler_e_normalizar


def _upload(data: bytes, content_type: str = "image/jpeg", filename: str = "foto.jpg") -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=filename, headers=Headers({"content-type": content_type}))


def _img_bytes(fmt: str, size=(64, 48), **save_kw) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format=fmt, **save_kw)
    return buf.getvalue()


def _normalizar(upload):
    return asyncio.run(_ler_e_normalizar(upload))


def _png_header_only(width: int, height: int) -> bytes:
    """PNG minúsculo em bytes que declara dimensões gigantes (decompression bomb)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b"")


def test_text_file_renamed_to_jpg_is_rejected():
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(b"#!/bin/sh\nrm -rf /\n" * 20, "image/jpeg", "foto.jpg"))
    assert exc.value.kind == "imagem"


def test_svg_with_script_spoofed_as_png_is_rejected():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(svg, "image/png", "x.png"))
    assert exc.value.kind == "imagem"


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF", "WEBP"])
def test_real_image_in_other_format_spoofed_as_jpeg_is_rejected(fmt):
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(_img_bytes(fmt), "image/jpeg"))
    assert exc.value.kind == "imagem"
    assert fmt in exc.value.message or "JPEG" in exc.value.message


def test_disallowed_content_type_is_rejected_before_reading():
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(_img_bytes("JPEG"), "application/octet-stream"))
    assert exc.value.kind == "imagem"


def test_empty_upload_is_rejected():
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(b""))
    assert exc.value.kind == "imagem"


def test_oversized_bytes_are_rejected_with_413_kind(monkeypatch):
    monkeypatch.setattr(config, "MAX_IMAGE_BYTES", 1024)
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(b"\xff\xd8" + b"0" * 4096))
    assert exc.value.kind == "imagem_grande"


@pytest.mark.parametrize("dims", [(6000, 6000), (40000, 40000)])
def test_decompression_bomb_is_rejected_without_500(dims):
    # 36 MP passa do teto do PoV (25 MP); 1.6 GP passa do limite do Pillow e antes
    # levantava DecompressionBombError fora do except (500 com stack trace).
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(_png_header_only(*dims), "image/png"))
    assert exc.value.kind == "imagem"


def test_truncated_jpeg_is_rejected():
    data = _img_bytes("JPEG", size=(400, 300))
    with pytest.raises(SafeQueryError) as exc:
        _normalizar(_upload(data[: len(data) // 3]))
    assert exc.value.kind == "imagem"


def test_exif_is_stripped_and_orientation_applied():
    img = Image.new("RGB", (80, 40), (10, 200, 10))
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    exif[0x010F] = "A" * 4000  # Make: blob longo
    exif[0x8825] = {1: "S", 2: (23.0, 33.0, 0.0)}  # GPSInfo (PII de localização)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    pil, jpeg = _normalizar(_upload(buf.getvalue()))

    out = Image.open(io.BytesIO(jpeg))
    assert out.format == "JPEG"
    assert not out.getexif(), "nenhum metadado EXIF (GPS, aparelho) pode sair da normalização"
    assert out.size == (40, 80), "orientação EXIF aplicada antes de descartar o EXIF"


def test_malicious_filename_is_never_used():
    # O nome do arquivo não entra na chave de storage; a normalização nem o lê.
    pil, jpeg = _normalizar(_upload(_img_bytes("PNG"), "image/png", "../../../../etc/passwd.jpg"))
    assert jpeg[:2] == b"\xff\xd8"


def test_png_and_phone_mpo_are_accepted_and_normalized_to_jpeg():
    for data, ct in [(_img_bytes("PNG"), "image/png"), (_img_bytes("JPEG"), "image/jpg")]:
        _, jpeg = _normalizar(_upload(data, ct))
        assert Image.open(io.BytesIO(jpeg)).format == "JPEG"
