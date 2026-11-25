"""Find the speaking character's name when the game shows it in a different colour
(e.g. "Jason" in yellow, then the line in white) instead of, or as well as, "Jason:"."""
from __future__ import annotations

from PIL import Image

from .extract import Line

COLOR_GAP = 70.0  # RGB distance that counts as "a different colour"


def word_color(img: Image.Image, box) -> tuple[int, int, int] | None:
    """Colour of the text strokes inside a word box: the median of its brightest pixels."""
    x0, y0, x1, y1 = int(box.left), int(box.top), int(box.right), int(box.bottom)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    region = img.crop((max(0, x0), max(0, y0), min(img.width, x1), min(img.height, y1))).convert("RGB")
    if region.width * region.height > 6000:
        region = region.resize((max(3, region.width // 2), max(3, region.height // 2)))
    raw = region.tobytes()
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    if not px:
        return None
    px.sort(key=lambda p: p[0] * 299 + p[1] * 587 + p[2] * 114, reverse=True)
    top = px[: max(3, len(px) // 6)]
    top.sort(key=lambda p: p[0] + p[1] + p[2])
    return top[len(top) // 2]


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def mark_coloured_speaker(img: Image.Image, line: Line) -> Line:
    """If the first 1-3 words are a different colour from the rest, rewrite as "Name: rest"."""
    words = list(line.words)
    if len(words) < 2 or ":" in line.text.split(" ")[0]:
        return line
    colours = [word_color(img, w.box) for w in words]
    if any(c is None for c in colours):
        return line
    tail = colours[len(colours) // 2:]
    base = tuple(sorted(c[i] for c in tail)[len(tail) // 2] for i in range(3))
    k = 0
    while k < min(3, len(words) - 1) and _dist(colours[k], base) > COLOR_GAP:
        k += 1
    if k == 0:
        return line
    # the name words must agree with each other
    if any(_dist(colours[i], colours[0]) > COLOR_GAP for i in range(1, k)):
        return line
    name = " ".join(w.text for w in words[:k]).rstrip(":：").strip()
    rest = " ".join(w.text for w in words[k:]).lstrip(":： ").strip()
    if not name or not rest or not name[0].isalpha():
        return line
    name = name[0].upper() + name[1:]
    return Line(f"{name}: {rest}", line.box, line.words)
