import io
import json

import pytest
from pypdf import PdfReader

from pdfsplitter import MM, web


def test_defaults():
    defaults = json.loads(web.defaults())
    assert defaults["options"] == {"paper": "a4", "overlap": 20, "margin": 0,
                                   "shrink": 10}
    assert defaults["papers"]["a4"] == [210, 297]


def test_read(tall_pdf):
    response = json.loads(web.read(tall_pdf))
    assert response == {"pages": [[447, 596], [447, 1800]], "title": None,
                        "annotations": 0}


def test_read_rotated_page():
    from conftest import make_pdf
    response = json.loads(web.read(make_pdf([((0, 0, 1500, 400), 90)])))
    assert response["pages"] == [[400, 1500]]


@pytest.mark.parametrize("data, error", [
    (b"\\documentclass{article}", "It is not a PDF."),
    (b"%PDF-1.7\nbroken", "Could not read the PDF"),
])
def test_read_error(data, error):
    assert json.loads(web.read(data))["error"].startswith(error)


def test_plan():
    response = json.loads(web.plan(json.dumps({
        "pages": [[447, 596], [447, 1800]],
        "options": {"paper": "a4", "overlap": "20", "margin": 5,
                    "unknown": True}})))
    assert response["paper"] == pytest.approx([210 * MM, 297 * MM])
    assert response["margin"] == pytest.approx(5 * MM)
    assert response["overlap"] == pytest.approx(20 * MM)
    assert response["max_overlap"] == pytest.approx(143.5)
    assert [len(_page["slices"]) for _page in response["pages"]] == [1, 3]
    assert [_page["left"] for _page in response["pages"]] == [0, 0]


def test_plan_error():
    response = json.loads(web.plan(json.dumps({
        "pages": [[100, 100]], "options": {"overlap": 500}})))
    assert "overlap must be between" in response["error"]


def test_split(tall_pdf):
    data = web.split(tall_pdf, json.dumps({"options": {"paper": "letter"}}))
    reader = PdfReader(io.BytesIO(data))
    # a page of a reMarkable is a bit too high for Letter, and shrunk
    assert len(reader.pages) == 4
    assert float(reader.pages[0].mediabox.height) == pytest.approx(792)
