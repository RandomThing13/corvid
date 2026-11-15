"""Native PDF evidence only. Text coordinates follow PyMuPDF's unrotated page space."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw
import pymupdf as fitz
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "data/raw/junction-dataset-preview/data"
DEVELOPMENT_PDF = SOURCE_ROOT / "swiss_dwellings/site1000_bldg2082_floor9385.pdf"
OUTPUT_ROOT = ROOT / "output/native"


class DocumentError(ValueError):
    """Unreadable, unsupported or ambiguous document evidence."""


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    basis: str = "printed area"
    room_identifier: str
    value: float
    unit: str = "m2"
    original_text: str
    room_text: str
    page_index: int
    source_path: str
    source_sha256: str
    room_rect: list[float]
    area_rect: list[float]
    room_display_normalized: list[float]
    area_display_normalized: list[float]
    transform: dict
    image_path: str
    page_image_path: str
    native_text_path: str
    association: str


def source_path(path: str | Path) -> Path:
    """Only resolved PDFs inside the document root can enter runtime extraction."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(SOURCE_ROOT.resolve()) or resolved.suffix.lower() != ".pdf":
        raise DocumentError("Only PDF documents within the configured source root are allowed")
    if not resolved.is_file():
        raise DocumentError("Source PDF is missing")
    return resolved


def rect_to_pixels(rect, rotation, render, pix_origin=(0, 0)) -> list[float]:
    displayed = fitz.Rect(rect) * rotation * render
    return [displayed.x0 - pix_origin[0], displayed.y0 - pix_origin[1],
            displayed.x1 - pix_origin[0], displayed.y1 - pix_origin[1]]


def normalized(rect, width, height):
    return [rect[0] / width, rect[1] / height, rect[2] / width, rect[3] / height]


def extract_native(page):
    words = [{"id": f"p{page.number}-b{w[5]}-l{w[6]}-w{w[7]}", "text": w[4],
              "rect": list(w[:4]), "block": w[5], "line": w[6]} for w in page.get_text("words")]
    spans = []
    for bi, block in enumerate(page.get_text("dict")["blocks"]):
        for li, line in enumerate(block.get("lines", [])):
            for si, span in enumerate(line["spans"]):
                spans.append({"id": f"p{page.number}-b{bi}-l{li}-s{si}", "text": span["text"],
                              "rect": list(span["bbox"]), "font_size": span["size"], "direction": list(line["dir"])})
    return words, spans


def locate_printed_area(words, spans, room_identifier):
    rooms = [w for w in words if w["text"] == room_identifier]
    if len(rooms) != 1:
        raise DocumentError(f"Expected one room identifier, found {len(rooms)}")
    room = rooms[0]
    r = fitz.Rect(room["rect"])
    candidates = []
    for span in spans:
        match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(?:m(?:²|2|\^2)|sqm|square\s+met(?:er|re)s?)\s*", span["text"])
        if not match:
            continue
        a = fitz.Rect(span["rect"])
        # Same centered label stack, at most two text heights below the room ID.
        gap = a.y0 - r.y1
        offset = abs((a.x0 + a.x1 - r.x0 - r.x1) / 2)
        if -0.2 * r.height <= gap <= 2 * r.height and offset <= r.height:
            candidates.append((math.hypot(offset, gap), span, float(match[1].replace(",", "."))))
    if len(candidates) != 1:
        raise DocumentError(f"Expected one spatially associated printed area, found {len(candidates)}")
    _, area, value = candidates[0]
    return room, area, value


def build_evidence(path: str | Path = DEVELOPMENT_PDF, room_identifier: str = "2.01", *, output_dir: Path = OUTPUT_ROOT, scale: float = 2) -> Evidence:
    path = source_path(path)
    if not 0.5 <= scale <= 4:
        raise DocumentError("Render scale must be between 0.5 and 4")
    try:
        document = fitz.open(path)
    except (fitz.FileDataError, RuntimeError) as exc:
        raise DocumentError("Cannot open source PDF") from exc
    with document:
        if not document.is_pdf or document.needs_pass or len(document) == 0:
            raise DocumentError("Expected an unencrypted, nonempty PDF")
        matches = []
        for page in document:
            words, spans = extract_native(page)
            if any(w["text"] == room_identifier for w in words):
                matches.append((page.number, words, spans))
        if len(matches) != 1:
            raise DocumentError(f"Expected room on one page, found {len(matches)} pages")
        page_index, words, spans = matches[0]
        page = document[page_index]
        room, area, value = locate_printed_area(words, spans, room_identifier)
        render = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=render, alpha=False, annots=False)
        pixels = [rect_to_pixels(x["rect"], page.rotation_matrix, render, (pix.x, pix.y)) for x in (room, area)]
        output_dir.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        # Content/room identity keeps derived artifacts distinct across inputs.
        suffix = hashlib.sha256(room_identifier.encode()).hexdigest()[:8]
        stem = f"{sha[:16]}-p{page_index}-r{suffix}-s{scale:g}"
        plain = output_dir / f"{stem}-page.png"
        highlighted = output_dir / f"{stem}-evidence.png"
        native = output_dir / f"{stem}-native.json"
        pix.save(plain)
        with Image.open(plain) as original:
            image = original.convert("RGB")
        draw = ImageDraw.Draw(image)
        for rectangle, color in zip(pixels, ("#0066ff", "#e63518")):
            draw.rectangle(rectangle, outline=color, width=2)
        image.save(highlighted)
        import json
        native.write_text(json.dumps({"page_index": page_index, "coordinate_space": "unrotated PyMuPDF page points", "words": words, "spans": spans}, indent=2) + "\n")
        return Evidence(
            room_identifier=room_identifier, value=value, original_text=area["text"], room_text=room["text"],
            page_index=page_index, source_path=str(path.relative_to(ROOT)), source_sha256=sha,
            room_rect=room["rect"], area_rect=area["rect"],
            room_display_normalized=normalized(pixels[0], pix.width, pix.height),
            area_display_normalized=normalized(pixels[1], pix.width, pix.height),
            transform={
                "native_space": "PyMuPDF unrotated top-left page points, already adjusted for CropBox",
                "raw_pdf_to_native_matrix": list(page.transformation_matrix),
                "cropbox": list(page.cropbox), "cropbox_position": list(page.cropbox_position), "mediabox": list(page.mediabox),
                "rotation_degrees": page.rotation, "native_to_display_matrix": list(page.rotation_matrix),
                "display_to_render_matrix": list(render), "native_to_render_matrix": list(page.rotation_matrix * render),
                "pixmap_origin": [pix.x, pix.y], "render_size": [pix.width, pix.height],
                "normalized_formula": "native rect * rotation_matrix * render_matrix; subtract pixmap origin; divide x by pixel width and y by pixel height",
                "room_pixel_rect": pixels[0], "area_pixel_rect": pixels[1],
            }, image_path=str(highlighted.resolve()), page_image_path=str(plain.resolve()), native_text_path=str(native.resolve()),
            association="Unique printed m2 span centered within one room-text height horizontally and zero to two heights below the identifier; ambiguous/missing matches fail closed.",
        )
