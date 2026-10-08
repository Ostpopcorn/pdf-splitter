import io

import pytest
from pypdf import PdfReader, PdfWriter

from conftest import make_pdf
from pdfsplitter import (MM, Options, layout_page, max_overlap, paper_size,
                         split_pdf)
from pdfsplitter.__main__ import main

A4 = (210 * MM, 297 * MM)


def test_paper_size():
    assert paper_size(Options()) == pytest.approx(A4)
    assert paper_size(Options(paper="Letter")) == pytest.approx((612, 792))
    with pytest.raises(ValueError, match="Unknown paper"):
        paper_size(Options(paper="b5"))


def test_page_that_fits():
    layout = layout_page(447, 596)
    assert layout.scale == pytest.approx(A4[0] / 447)
    assert layout.slices == [(0, pytest.approx(A4[1] / layout.scale))]


def test_tall_page():
    layout = layout_page(447, 1800, Options(overlap=20))
    size = A4[1] / layout.scale
    overlap = 20 * MM / layout.scale
    assert len(layout.slices) == 3
    for (_top, _bottom), (_next, _) in zip(layout.slices, layout.slices[1:]):
        assert _bottom - _top == pytest.approx(size)
        # the end of a slice is repeated at the top of the next one
        assert _bottom - _next == pytest.approx(overlap)
    assert layout.slices[-1][1] >= 1800
    # two slices would not be enough
    assert layout.slices[-2][1] < 1800


def test_no_overlap():
    layout = layout_page(100, 1000, Options(overlap=0))
    assert all(_bottom == pytest.approx(_next) for (_, _bottom), (_next, _)
               in zip(layout.slices, layout.slices[1:]))


def test_exact_fit_adds_no_page():
    # a page as high as two slices with the overlap
    scale = A4[0] / 400
    height = (2 * A4[1] - 20 * MM) / scale
    options = Options(shrink=0)
    assert len(layout_page(400, height, options).slices) == 2
    assert len(layout_page(400, height + 1, options).slices) == 3
    assert len(layout_page(400, A4[1] / scale, options).slices) == 1


def test_shrink_a_page_that_is_a_bit_too_long():
    # a page of a reMarkable is a bit too long for Letter
    letter = Options(paper="letter")
    layout = layout_page(447, 596, letter)
    assert layout.scale == pytest.approx(792 / 596)
    assert layout.slices == [(0, pytest.approx(596))]
    assert layout.left == pytest.approx((612 - 447 * layout.scale) / 2)
    assert layout.left > 0
    unshrunk = layout_page(447, 596, Options(paper="letter", shrink=0))
    assert unshrunk.scale == pytest.approx(612 / 447)
    assert len(unshrunk.slices) == 2 and unshrunk.left == 0
    # 3 % smaller is too much
    assert len(layout_page(447, 596, Options(paper="letter", shrink=2)).slices) == 2


def test_shrink_a_long_page():
    scale = A4[0] / 400
    overlap = 20 * MM
    # 5 % longer than two pages with the overlap
    height = (2 * A4[1] - overlap) / scale * 1.05
    layout = layout_page(400, height)
    assert len(layout.slices) == 2
    assert layout.scale == pytest.approx(scale / 1.05)
    (top, bottom), (next_top, next_bottom) = layout.slices
    assert (bottom - next_top) * layout.scale == pytest.approx(overlap)
    assert next_bottom == pytest.approx(height)
    # 15 % longer
    assert len(layout_page(400, height / 1.05 * 1.15).slices) == 3
    assert len(layout_page(400, height / 1.05 * 1.15, Options(shrink=15)).slices) == 2


def test_margin():
    layout = layout_page(400, 400, Options(margin=10))
    assert layout.scale == pytest.approx((A4[0] - 20 * MM) / 400)


def test_wide_page_fits_the_width():
    layout = layout_page(1000, 300)
    assert layout.scale == pytest.approx(A4[0] / 1000)
    assert len(layout.slices) == 1


@pytest.mark.parametrize("options, message", [
    (Options(overlap=-1), "overlap"),
    (Options(overlap=149), "overlap must be between 0 and 148 mm"),
    (Options(margin=10, overlap=139), "overlap must be between 0 and 138 mm"),
    (Options(margin=-1), "margin"),
    (Options(margin=105), "margin"),
    (Options(shrink=-1), "shrink"),
    (Options(shrink=60), "shrink"),
])
def test_invalid_options(options, message):
    with pytest.raises(ValueError, match=message):
        layout_page(100, 100, options)


def test_max_overlap():
    assert max_overlap(Options()) == pytest.approx(148.5)
    assert max_overlap(Options(paper="a5", margin=5)) == pytest.approx(100)


def test_split_pdf(tall_pdf):
    result = split_pdf(tall_pdf)
    assert result.pages == 4
    assert [len(_layout.slices) for _layout in result.layouts] == [1, 3]
    reader = PdfReader(io.BytesIO(result.data))
    assert len(reader.pages) == 4
    for _page in reader.pages:
        assert [float(_value) for _value in _page.mediabox] == pytest.approx(
            [0, 0, *A4])
    # each page is in the PDF once, as a form XObject that the slices show
    forms = {_page["/Resources"]["/XObject"].raw_get("/Page").idnum
             for _page in reader.pages}
    assert len(forms) == 2
    form = reader.pages[1]["/Resources"]["/XObject"]["/Page"]
    assert form["/Subtype"] == "/Form"
    assert [float(_value) for _value in form["/BBox"]] == [0, 0, 447, 1800]
    assert form.get_data().startswith(b"0 g\n")


def test_split_pdf_keeps_the_title():
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf([((0, 0, 100, 100), 0)])))
    writer.add_metadata({"/Title": "Notes"})
    data = io.BytesIO()
    writer.write(data)
    result = split_pdf(data.getvalue())
    assert PdfReader(io.BytesIO(result.data)).metadata.title == "Notes"


def test_password():
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf([((0, 0, 100, 100), 0)])))
    writer.encrypt("secret", algorithm="RC4-128")
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match="password"):
        split_pdf(data.getvalue())


def test_empty_user_password():
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf([((0, 0, 100, 100), 0)])))
    writer.encrypt("", "owner", algorithm="RC4-128")
    data = io.BytesIO()
    writer.write(data)
    assert split_pdf(data.getvalue()).pages == 1


def test_cli(tmp_path, tall_pdf, capsys):
    source = tmp_path / "notes.pdf"
    source.write_bytes(tall_pdf)
    main([str(source), "--overlap", "30", "--paper", "A5", "--shrink", "0"])
    reader = PdfReader(str(tmp_path / "notes-a5.pdf"))
    assert float(reader.pages[0].mediabox.width) == pytest.approx(148 * MM)
    assert "with 5 pages from 2 pages, of which 1 split" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main([str(source), "--overlap", "200"])
    with pytest.raises(SystemExit):
        main([str(source), "-o", str(source)])


# Render the original and the new PDF, and compare each slice with the part of
# the original that it shows

def _render(pdfium, data, scale):
    document = pdfium.PdfDocument(data)
    # gray pixels as an array, without Pillow
    return [document[_i].render(scale=scale, grayscale=True).to_numpy().astype(int)
            for _i in range(len(document))]


def _neighbors(numpy, image):
    """The darkest and the lightest pixel around each pixel, so that the
    images may differ by a pixel where the edges are rounded differently."""
    padded = numpy.pad(image, 1, mode="edge")
    shifted = [padded[_y:_y + image.shape[0], _x:_x + image.shape[1]]
               for _y in range(3) for _x in range(3)]
    return numpy.min(shifted, axis=0), numpy.max(shifted, axis=0)


@pytest.mark.parametrize("box, rotation", [
    ((0, 0, 400, 1500), 0),
    ((-50, 30, 350, 1530), 0),
    ((0, 0, 1500, 400), 90),
    ((20, -10, 420, 1490), 180),
    ((0, 0, 1500, 400), 270),
    ((0, 0, 400, 500), 0),
    # shrunk to fit on one page
    ((0, 0, 400, 590), 0),
    ((0, 0, 400, 1160), 0),
])
@pytest.mark.parametrize("margin", [0, 12])
def test_rendered_slices(box, rotation, margin):
    pdfium = pytest.importorskip("pypdfium2")
    numpy = pytest.importorskip("numpy")
    source = make_pdf([(box, rotation)])
    result = split_pdf(source, Options(overlap=25, margin=margin))
    layout = result.layouts[0]
    resolution = 0.5  # pixels per point of the original
    original = _render(pdfium, source, resolution)[0]
    assert original.shape == (round(layout.height * resolution),
                              round(layout.width * resolution))
    pages = _render(pdfium, result.data, resolution / layout.scale)
    assert len(pages) == len(layout.slices) > 0
    edge = round(margin * MM * resolution / layout.scale)
    left = edge + round(layout.left * resolution / layout.scale)
    for page, (_top, _bottom) in zip(pages, layout.slices):
        top = round(_top * resolution)
        rows = min(round(_bottom * resolution), original.shape[0]) - top
        width = original.shape[1]
        shown = page[edge:edge + rows, left:left + width]
        expected = original[top:top + rows]
        assert shown.shape == expected.shape
        assert expected.min() < 100  # there are bars to compare
        darkest, lightest = _neighbors(numpy, expected)
        wrong = (shown < darkest - 60) | (shown > lightest + 60)
        assert wrong.mean() < 0.001
        # the margins and the paper below the page stay empty, but for the
        # pixels at the edges, which are rounded
        empty = page.copy()
        empty[max(0, edge - 2):edge + rows + 2,
              max(0, left - 2):left + width + 2] = 255
        assert empty.min() > 250
