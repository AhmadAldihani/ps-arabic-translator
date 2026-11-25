"""Text recognition with the OCR engine built into Windows 10/11 (offline, fast, free)."""
from __future__ import annotations

import asyncio

from PIL import Image

from .extract import Box, Line

LANG_TAGS = {"en": "en-US", "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "it": "it-IT", "pt": "pt-BR"}


class OcrUnavailable(RuntimeError):
    pass


class WindowsOcr:
    def __init__(self, lang: str = "en"):
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
        except ImportError as e:  # not on Windows, or packages missing
            raise OcrUnavailable(f"Windows OCR is not available: {e}") from e
        tag = LANG_TAGS.get(lang, lang)
        engine = None
        if OcrEngine.is_language_supported(Language(tag)):
            engine = OcrEngine.try_create_from_language(Language(tag))
        if engine is None:
            for l in OcrEngine.available_recognizer_languages:
                if l.language_tag.lower().startswith(lang.lower()):
                    engine = OcrEngine.try_create_from_language(l)
                    break
        if engine is None:
            have = ", ".join(l.language_tag for l in OcrEngine.available_recognizer_languages) or "none"
            raise OcrUnavailable(
                f"Windows has no OCR for '{tag}' (installed: {have}). "
                "Add the language in Settings > Time & language > Language & region.")
        self.engine = engine
        self.lang = lang

    def read(self, img: Image.Image) -> list[Line]:
        """Lines with boxes in the pixels of [img]."""
        scale = 1.0
        # Windows OCR likes text at least ~20px tall; subtitles in a 720p stream are smaller.
        if img.width < 1600:
            scale = min(3.0, 1600 / img.width)
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        result = asyncio.run(self._recognize(img))
        lines: list[Line] = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            wl = []
            for w in words:
                r = w.bounding_rect
                wl.append(Line(w.text, Box(r.x / scale, r.y / scale, (r.x + r.width) / scale, (r.y + r.height) / scale)))
            box = Box(min(x.box.left for x in wl), min(x.box.top for x in wl),
                      max(x.box.right for x in wl), max(x.box.bottom for x in wl))
            lines.append(Line(line.text, box, tuple(wl)))
        return lines

    async def _recognize(self, img: Image.Image):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        rgba = img.convert("RGBA")
        r, g, b, a = rgba.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        writer = DataWriter()
        writer.write_bytes(bgra)
        bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8,
                                                        img.width, img.height)
        return await self.engine.recognize_async(bitmap)
