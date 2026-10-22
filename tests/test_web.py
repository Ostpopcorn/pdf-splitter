import io
import json

import pytest
from pypdf import PdfReader

from pdfsplitter import MM, web


def test_defaults():
    defaults = json.loads(web.defaults())
    assert defaults["options"] == {"paper": "a4", "overlap": 20, "margin": 0,
                                   "shrink": 10, "turn": True, "poster": False,
                                   "scale": 100, "center": False}
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
    assert response["max_overlap"] == pytest.approx(100)
    assert [len(_page["slices"]) for _page in response["pages"]] == [1, 3]
    assert [_page["left"] for _page in response["pages"]] == [0, 0]
    assert [len(_page["columns"]) for _page in response["pages"]] == [1, 1]
    assert response["pages"][0]["paper"] == pytest.approx(response["paper"])
    assert response["poster"] is False


def test_plan_poster():
    response = json.loads(web.plan(json.dumps({
        "pages": [[420 * MM, 594 * MM], [596, 447]],
        "options": {"poster": True, "scale": "100", "turn": True}})))
    assert response["poster"] is True
    poster, small = response["pages"]
    assert poster["scale"] == 1
    assert (len(poster["columns"]), len(poster["slices"])) == (2, 4)
    assert poster["paper"] == pytest.approx([297 * MM, 210 * MM])
    assert (len(small["columns"]), len(small["slices"])) == (1, 1)


def test_plan_error():
    response = json.loads(web.plan(json.dumps({
        "pages": [[100, 100]], "options": {"overlap": 500}})))
    assert "overlap must be between" in response["error"]


def test_split(tall_pdf):
    data = web.split([tall_pdf], json.dumps({"options": {"paper": "letter"}}))
    reader = PdfReader(io.BytesIO(data))
    # a page of a reMarkable is a bit too high for Letter, and shrunk
    assert len(reader.pages) == 4
    assert float(reader.pages[0].mediabox.height) == pytest.approx(792)
