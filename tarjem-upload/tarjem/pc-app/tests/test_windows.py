"""Runs only on Windows (the CI build machine): real Windows OCR and window listing."""
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_windows_ocr_reads_a_subtitle():
    from tarjem.extract import extract
    from tarjem.ocr import WindowsOcr

    img = Image.new("RGB", (1280, 240), (20, 30, 25))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    d.text((300, 80), "We have to leave before the", font=font, fill=(255, 255, 255))
    d.text((320, 125), "storm reaches the village.", font=font, fill=(255, 255, 255))
    lines = WindowsOcr("en").read(img)
    sub = extract(lines, img.width, 720, True)
    assert sub is not None, lines
    assert "storm reaches the village" in sub.text.lower()
    assert 250 < sub.box.left < 360 and 60 < sub.box.top < 100


def test_list_windows_does_not_crash():
    from tarjem import capture
    assert isinstance(capture.list_windows(), list)
