from pathlib import Path
import math

from fastapi.testclient import TestClient
from PIL import Image
import pymupdf as fitz
import pytest

from app import ingest
from app.main import app


@pytest.fixture(scope="module")
def real_evidence(tmp_path_factory):
    return ingest.build_evidence(output_dir=tmp_path_factory.mktemp("real-evidence"))


def test_real_native_evidence(real_evidence):
    e = real_evidence
    assert e.basis == "printed area"
    assert e.original_text == "15.61 m²"  # Development-only sanity check.
    assert e.value == 15.61
    assert e.page_index == 0
    with fitz.open(ingest.DEVELOPMENT_PDF) as document:
        page = document[0]
        assert page.get_textbox(fitz.Rect(e.room_rect)).strip() == "2.01"
        assert page.get_textbox(fitz.Rect(e.area_rect)).strip() == e.original_text
    assert len(e.source_sha256) == 64


def test_real_rectangles_cover_rendered_text(real_evidence):
    e = real_evidence
    with Image.open(e.page_image_path) as image:
        assert list(image.size) == e.transform["render_size"]
        for key, norm in (("room_pixel_rect", e.room_display_normalized), ("area_pixel_rect", e.area_display_normalized)):
            box = e.transform[key]
            assert 0 <= min(norm) < max(norm) <= 1
            reconstructed = [norm[0]*image.width, norm[1]*image.height, norm[2]*image.width, norm[3]*image.height]
            assert reconstructed == pytest.approx(box, abs=1e-5)
            crop = image.crop((math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3]))).convert("L")
            dark = sum(v < 150 for v in crop.getdata())
            assert dark > 20  # Actual glyph pixels occupy each evidence rectangle.
    with Image.open(e.image_path) as image:
        x, y, _, _ = e.transform["area_pixel_rect"]
        assert image.getpixel((int(x), int(y))) == (230, 53, 24)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_rotation_alignment_against_rendered_marker(rotation):
    # Independent raster oracle: find the colored marker, not a recomputed matrix.
    with fitz.open() as document:
        page = document.new_page(width=400, height=300)
        page.draw_rect(fitz.Rect(110, 90, 150, 120), color=None, fill=(1, 0, 0))
        page.set_cropbox(fitz.Rect(40, 30, 360, 270))
        page.set_rotation(rotation)
        page = document.reload_page(page)
        render = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=render, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        red = [(i % image.width, i // image.width) for i, (r,g,b) in enumerate(image.getdata()) if r > 230 and g < 20 and b < 20]
        raster_box = [min(x for x,y in red), min(y for x,y in red), max(x for x,y in red)+1, max(y for x,y in red)+1]
        # Crop-relative, unrotated native space of the known source marker.
        predicted = ingest.rect_to_pixels([70,60,110,90], page.rotation_matrix, render, (pix.x,pix.y))
        assert predicted == pytest.approx(raster_box, abs=1)


def test_corrupted_pdf_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "SOURCE_ROOT", tmp_path)
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"This is not a PDF")
    with pytest.raises(ingest.DocumentError, match="Cannot open source PDF"):
        ingest.build_evidence(bad, output_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_missing_and_ambiguous_room_fail():
    with pytest.raises(ingest.DocumentError, match="found 0"):
        ingest.locate_printed_area([], [], "2.01")
    words = [{"text": "2.01", "rect": [10,10,20,20]}]
    spans = [{"text": "8.5 m²", "rect": [8,21,22,30]}, {"text": "9.1 m²", "rect": [8,22,22,31]}]
    with pytest.raises(ingest.DocumentError, match="found 2"):
        ingest.locate_printed_area(words, spans, "2.01")


def test_area_value_is_source_derived():
    room, span, value = ingest.locate_printed_area(
        [{"text":"A7", "rect":[10,10,20,20]}],
        [{"text":"27,43 m²", "rect":[5,21,25,31]}], "A7")
    assert value == 27.43
    assert span["text"] == "27,43 m²"


def test_private_labels_and_path_escape_rejected(tmp_path, monkeypatch):
    for path in (ingest.ROOT / "data/eval_private/questions.jsonl", ingest.SOURCE_ROOT / "../../eval_private/questions.jsonl"):
        with pytest.raises(ingest.DocumentError, match="Only PDF"):
            ingest.source_path(path)
    source = tmp_path / "sources"
    source.mkdir()
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"private sentinel")
    (source / "linked.pdf").symlink_to(outside)
    monkeypatch.setattr(ingest, "SOURCE_ROOT", source)
    with pytest.raises(ingest.DocumentError, match="Only PDF"):
        ingest.source_path(source / "linked.pdf")


def test_runtime_never_opens_private_labels(monkeypatch):
    original = Path.open
    reads = []
    def guard(path, *args, **kwargs):
        resolved = path.resolve()
        assert "eval_private" not in resolved.parts
        assert resolved.name != "questions.jsonl"
        reads.append(resolved)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guard)
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        e = client.get("/development/evidence")
        assert e.status_code == 200
        assert e.json()["basis"] == "printed area"
        for endpoint in ("/development/page", "/development/highlight"):
            response = client.get(endpoint)
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content.startswith(b"\x89PNG")
    assert ingest.DEVELOPMENT_PDF.resolve() in reads
    for path in (ingest.ROOT / "app").glob("*.py"):
        text = path.read_text()
        assert "eval_private" not in text and "questions.jsonl" not in text
        assert "from scripts" not in text and "import scripts" not in text
