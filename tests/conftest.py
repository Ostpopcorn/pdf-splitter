import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import (DecodedStreamObject, NameObject, NumberObject,
                           RectangleObject)


def bars(box, count=12):
    """A content stream with black bars of different lengths in a box, so
    that each part of the page looks different."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    lines = ["0 g"]
    for _i in range(count):
        y = y0 + height * (_i + 0.3) / count
        length = width * (0.2 + 0.7 * ((_i * 5) % count) / count)
        lines.append("{:.2f} {:.2f} {:.2f} {:.2f} re f".format(
            x0 + width * 0.05, y, length, height / count * 0.4))
    # a diagonal line, which shows the rotation
    lines.append("4 w {} {} m {} {} l S".format(x0, y0, x1, y1))
    return "\n".join(lines).encode()


def make_pdf(pages):
    """A PDF with pages (box, rotation) and bars on each page."""
    writer = PdfWriter()
    for _box, _rotation in pages:
        page = writer.add_blank_page(100, 100)
        page[NameObject("/MediaBox")] = RectangleObject(_box)
        if _rotation:
            page[NameObject("/Rotate")] = NumberObject(_rotation)
        content = DecodedStreamObject()
        content.set_data(bars(_box))
        page.replace_contents(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def tall_pdf():
    """A PDF with a page that fits on A4 and a page that is three times as
    high, like notes from a reMarkable."""
    return make_pdf([((0, 0, 447, 596), 0), ((0, 0, 447, 1800), 0)])
