"""Phase 2: turn grant PDFs into chunks.

Two strategies, so we can measure which retrieves better (Phase 4/5):

  section  - find headings from font size / boldness, keep the heading path
             ("Eligibility > Cost Sharing Requirement") with each chunk, and
             never let a chunk cross from one section into the next.
  fixed    - baseline: ignore structure, cut the text every N words.

Both pack whole sentences up to `chunk_words`, with `overlap_words` of
trailing context repeated at the start of the next chunk.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

MAX_HEADING_CHARS = 120
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\d\"'])")
TOC_LEADER = re.compile(r"\.{4,}\s*\d+\s*$")  # "Eligibility ........ 12"
NO_LETTERS = re.compile(r"^[^A-Za-z]*$")


@dataclass
class Line:
    text: str
    size: float
    bold: bool
    page: int
    block: int  # lines in the same PDF block belong to one paragraph


@dataclass
class Section:
    path: list[str]
    lines: list[Line] = field(default_factory=list)


@dataclass
class Unit:
    """A sentence-sized piece of text, the smallest thing we pack into chunks."""
    text: str
    page: int

    @property
    def words(self) -> int:
        return len(self.text.split())


def normalize(text: str) -> str:
    # NFKC turns ligatures like "ﬃ" into "ffi" so keyword search can match them.
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_lines(pdf_path: Path) -> list[Line]:
    lines: list[Line] = []
    block_id = 0
    with fitz.open(pdf_path) as doc:
        for page_no, page in enumerate(doc, start=1):
            for block in page.get_text("dict")["blocks"]:
                block_id += 1
                for raw in block.get("lines", []):
                    spans = [s for s in raw["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    text = normalize("".join(s["text"] for s in raw["spans"]))
                    if not text or TOC_LEADER.search(text):
                        continue
                    lines.append(Line(
                        text=text,
                        size=round(max(s["size"] for s in spans) * 2) / 2,
                        bold=all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans),
                        page=page_no,
                        block=block_id,
                    ))
    return drop_repeated_headers(lines)


def drop_repeated_headers(lines: list[Line]) -> list[Line]:
    """Remove running headers/footers: the same line on many pages."""
    pages = {line.page for line in lines}
    if len(pages) < 4:
        return lines
    key = lambda line: re.sub(r"\d+", "#", line.text.lower())
    pages_per_key: dict[str, set[int]] = {}
    for line in lines:
        pages_per_key.setdefault(key(line), set()).add(line.page)
    repeated = {k for k, p in pages_per_key.items() if len(p) >= 0.4 * len(pages)}
    return [line for line in lines if key(line) not in repeated]


def body_font_size(lines: list[Line]) -> float:
    sizes = Counter()
    for line in lines:
        sizes[line.size] += len(line.text)
    return sizes.most_common(1)[0][0] if sizes else 0


def is_heading(line: Line, body_size: float) -> bool:
    text = line.text
    if len(text) > MAX_HEADING_CHARS or NO_LETTERS.match(text):
        return False
    if text[0].islower():  # a bold phrase mid-sentence, not a title
        return False
    if line.size >= body_size + 1.5:
        return True
    # Bold at body size: short label-like lines ("Cost Sharing Required?"),
    # but not bold lead-ins to a list ("Eligible costs include:").
    return (
        line.bold
        and line.size >= body_size - 0.5
        and len(text.split()) <= 12
        and not text.endswith((":", ",", ";"))
    )


def split_sections(lines: list[Line]) -> list[Section]:
    body_size = body_font_size(lines)
    sections: list[Section] = []
    stack: list[tuple[float, str]] = []  # (font size, heading text), outermost first
    current = Section(path=[])
    prev_heading: Line | None = None

    for line in lines:
        if is_heading(line, body_size):
            # A title wrapped onto two lines arrives as two heading lines in one block.
            if prev_heading and prev_heading.block == line.block and prev_heading.size == line.size:
                size, text = stack.pop()
                stack.append((size, f"{text} {line.text}"))
                current.path = [t for _, t in stack]
                prev_heading = line
                continue
            if current.lines:
                sections.append(current)
            while stack and stack[-1][0] <= line.size:
                stack.pop()
            stack.append((line.size, line.text))
            current = Section(path=[t for _, t in stack])
            prev_heading = line
        else:
            current.lines.append(line)
            prev_heading = None

    if current.lines:
        sections.append(current)
    return sections


def to_units(lines: list[Line]) -> list[Unit]:
    """Rebuild paragraphs from lines, then split paragraphs into sentences."""
    paragraphs: list[tuple[str, int, int]] = []  # (text, page, block)
    for line in lines:
        if paragraphs and paragraphs[-1][2] == line.block:
            text, page, block = paragraphs[-1]
            joined = text[:-1] + line.text if text.endswith("-") else f"{text} {line.text}"
            paragraphs[-1] = (joined, page, block)
        else:
            paragraphs.append((line.text, line.page, line.block))

    units = []
    for text, page, _ in paragraphs:
        units.extend(Unit(s, page) for s in SENTENCE_END.split(text) if s.strip())
    return units


def pack(units: list[Unit], chunk_words: int, overlap_words: int) -> list[list[Unit]]:
    """Greedily pack sentences into chunks of about chunk_words words."""
    chunks: list[list[Unit]] = []
    current: list[Unit] = []
    count = 0
    has_new = False  # False when `current` is only overlap carried from the last chunk
    for unit in split_long(units, chunk_words):
        if has_new and count + unit.words > chunk_words:
            chunks.append(current)
            current = tail(current, overlap_words)
            count = sum(u.words for u in current)
        current.append(unit)
        count += unit.words
        has_new = True
    if has_new:
        chunks.append(current)
    return chunks


def split_long(units: list[Unit], chunk_words: int) -> list[Unit]:
    """A 'sentence' longer than a chunk (tables, lists) is cut by word count."""
    out = []
    for unit in units:
        words = unit.text.split()
        if len(words) <= chunk_words:
            out.append(unit)
            continue
        for i in range(0, len(words), chunk_words):
            out.append(Unit(" ".join(words[i:i + chunk_words]), unit.page))
    return out


def tail(units: list[Unit], overlap_words: int) -> list[Unit]:
    kept: list[Unit] = []
    count = 0
    for unit in reversed(units):
        if count + unit.words > overlap_words:
            break
        kept.insert(0, unit)
        count += unit.words
    return kept


def chunk_pdf(
    pdf_path: Path,
    strategy: str = "section",
    chunk_words: int = 300,
    overlap_words: int = 50,
) -> list[dict]:
    lines = extract_lines(pdf_path)
    if strategy == "section":
        groups = [(" > ".join(s.path) or None, s.lines) for s in split_sections(lines)]
    elif strategy == "fixed":
        groups = [(None, lines)]
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    chunks = []
    for section, group_lines in groups:
        for units in pack(to_units(group_lines), chunk_words, overlap_words):
            text = " ".join(u.text for u in units)
            chunks.append({
                "chunk_index": len(chunks),
                "section": section,
                "page_start": units[0].page,
                "page_end": units[-1].page,
                "text": text,
                "n_words": len(text.split()),
            })
    return chunks
