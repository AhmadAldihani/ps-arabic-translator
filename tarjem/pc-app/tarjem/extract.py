"""Picks the subtitle out of everything OCR finds in the selected area.

Pure Python, no Windows APIs, so it is unit tested on any OS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_DIGIT = re.compile(r"\d")
_JUNK_EDGES = re.compile(r"^[\s|_~•·*#=<>\[\]{}]+|[\s|_~•·*#=<>\[\]{}]+$")
_SPACES = re.compile(r"\s+")
_KEY_STRIP = re.compile(r"[^\w ]", re.UNICODE)
_LEADING_PIPE = re.compile(r"^\|(?=\s+[^\W\d_])")
_INNER_PIPE = re.compile(r"(?<=\s)\|(?=\s+[^\W\d_])")
# "JASON: Stop it, Lucia" / "Lucia: ..." / "Mr. Hale: ..."  (1-3 capitalised words, then a colon)
_SPEAKER = re.compile(r"^((?:[A-Z][\w'’.\-]*)(?:\s+[A-Z0-9][\w'’.\-]*){0,2})\s*[:：]\s+(\S.*)$")
_DASH = re.compile(r"^[-–—]\s*")


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2

    def union(self, o: "Box") -> "Box":
        return Box(min(self.left, o.left), min(self.top, o.top), max(self.right, o.right), max(self.bottom, o.bottom))


@dataclass(frozen=True)
class Line:
    text: str
    box: Box
    words: tuple = ()   # tuple[Line, ...] — each word with its own box, when the OCR gives them


@dataclass(frozen=True)
class Subtitle:
    text: str   # what gets translated
    key: str    # normalised, for "same subtitle?" checks
    box: Box    # union of its lines, in the same pixels as the input
    line_height: float = 0.0  # average height of one English line, same pixels

    @property
    def utterances(self) -> list[tuple[str | None, str]]:
        """[(speaker or None, spoken text)], one per speaker line."""
        return [split_speaker(_DASH.sub("", l)) for l in self.text.split("\n") if l.strip()]


def split_speaker(line: str) -> tuple[str | None, str]:
    m = _SPEAKER.match(line.strip())
    if not m:
        return None, line.strip()
    name, body = m.group(1).strip(), m.group(2).strip()
    if len(name) < 2 or name.isdigit():
        return None, line.strip()
    return name, body


def clean_line(raw: str) -> str:
    s = raw.replace(" ", " ").strip()
    s = _LEADING_PIPE.sub("I", s)
    s = _INNER_PIPE.sub("I", s)
    s = _JUNK_EDGES.sub("", s)
    return _SPACES.sub(" ", s).strip()


def normalize(text: str) -> str:
    return _SPACES.sub(" ", _KEY_STRIP.sub(" ", text.lower().replace("_", " "))).strip()


def similarity(a: str, b: str) -> float:
    """1.0 identical .. 0.0 nothing in common (normalised Levenshtein)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def join_for_translation(lines: list[str]) -> str:
    """Wrapped lines become one sentence; a leading dash means a new speaker."""
    out = ""
    for line in lines:
        if not out:
            out = line
        elif line[:1] in "-–—" or _SPEAKER.match(line):
            out += "\n" + line
        elif out.endswith("-") and not out.endswith(" -"):
            out = out[:-1] + line
        else:
            out += " " + line
    return out


def useful(text: str, box: Box, width: float, height: float, centered_only: bool) -> bool:
    letters = len(_LETTER.findall(text))
    if letters < 2:
        return False
    if len(_DIGIT.findall(text)) > letters:
        return False
    if height > 0 and box.height < height * 0.012:
        return False
    if centered_only and width > 0:
        c = box.cx / width
        if c < 0.25 or c > 0.75:
            return False
    return True


def extract_all(raw: list[Line], width: float, height: float, centered_only: bool = True,
                min_letters: int = 4) -> list[Subtitle]:
    """Every subtitle block in the area (top to bottom), e.g. two speakers shown at once."""
    groups = _groups(raw, width, height, centered_only)
    out = []
    for g in groups:
        if sum(len(_LETTER.findall(l.text)) for l in g) < min_letters:
            continue
        sub = _to_subtitle(g)
        if sub:
            out.append(sub)
    return out


def _to_subtitle(g: list[Line]) -> Subtitle | None:
    text = join_for_translation([l.text for l in g])
    key = normalize(text)
    if not key:
        return None
    box = g[0].box
    for l in g[1:]:
        box = box.union(l.box)
    return Subtitle(text, key, box, sum(l.box.height for l in g) / len(g))


def _groups(raw: list[Line], width: float, height: float, centered_only: bool) -> list[list[Line]]:
    lines = [Line(clean_line(l.text), l.box, l.words) for l in raw]
    lines = [l for l in lines if useful(l.text, l.box, width, height, centered_only)]
    lines.sort(key=lambda l: l.box.top)
    groups: list[list[Line]] = []
    for line in lines:
        if groups and _belongs(groups[-1], line, width):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def extract(raw: list[Line], width: float, height: float, centered_only: bool = True) -> Subtitle | None:
    lines = [Line(clean_line(l.text), l.box) for l in raw]
    lines = [l for l in lines if useful(l.text, l.box, width, height, centered_only)]
    if not lines:
        return None
    lines.sort(key=lambda l: l.box.top)

    groups: list[list[Line]] = []
    for line in lines:
        if groups and _belongs(groups[-1], line, width):
            groups[-1].append(line)
        else:
            groups.append([line])

    def score(g: list[Line]):
        return (sum(len(_LETTER.findall(l.text)) for l in g), g[-1].box.bottom)

    best = max(groups, key=score)
    text = join_for_translation([l.text for l in best])
    key = normalize(text)
    if not key:
        return None
    box = best[0].box
    for l in best[1:]:
        box = box.union(l.box)
    return Subtitle(text, key, box)


def _belongs(group: list[Line], line: Line, width: float) -> bool:
    prev = group[-1]
    gap = line.box.top - prev.box.bottom
    if gap > max(prev.box.height, line.box.height) * 1.3:
        return False
    center = sum(l.box.cx for l in group) / len(group)
    return abs(line.box.cx - center) < width * 0.25
