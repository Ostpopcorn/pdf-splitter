import io
import json

import pypdfium2
import pytest
from pypdf import PdfReader

from pdfsplitter import Options, image_pdf, split_pdf, web


def _image(data):
    """The image on the only page of a PDF, and the size of the page."""
    page = PdfReader(io.BytesIO(data)).pages[0]
    image = page["/Resources"]["/XObject"]["/Image"].get_object()
    return image, (float(page.mediabox.width), float(page.mediabox.height))


def test_gray():
    # a gradient in RGB, which is stored as gray
    gray = bytes(range(200)) * 3
    pixels = bytes(_value for _value in gray for _ in range(3))
    image, size = _image(image_pdf(pixels, 20, 30))
    assert image["/ColorSpace"] == "/DeviceGray"
    assert (image["/Width"], image["/Height"]) == (20, 30)
    assert image.get_data() == gray
    assert size == pytest.approx((20 * 72 / 226, 30 * 72 / 226))


def test_color():
    pixels = bytes([255, 255, 255] * 11 + [200, 30, 10])
    image, size = _image(image_pdf(pixels, 4, 3, resolution=72))
    assert image["/ColorSpace"] == "/DeviceRGB"
    assert image.get_data() == pixels
    assert size == (4, 3)


@pytest.mark.parametrize("width, height", [(4, 4), (0, 4), (3, 0)])
def test_wrong_size(width, height):
    with pytest.raises(ValueError):
        image_pdf(bytes(3 * 3 * 4), width, height)


def test_upright():
    # dark at the top, light at the bottom
    pixels = bytes([20] * 40 * 30 * 3 + [240] * 40 * 30 * 3)
    data = image_pdf(pixels, 40, 60, resolution=72)
    page = pypdfium2.PdfDocument(data)[0]
    rendered = page.render(scale=1, grayscale=True).to_numpy()
    assert rendered.shape[:2] == (60, 40)
    assert rendered[5:25, 5:35].max() < 60
    assert rendered[35:55, 5:35].min() > 200


def test_split_tall_image():
    # a page of a reMarkable that is three screens long
    width, height = 1404, 3 * 1872
    data = image_pdf(bytes([255]) * width * height * 3, width, height)
    result = split_pdf(data, Options(paper="a4", overlap=20))
    assert [len(_layout.slices) for _layout in result.layouts] == [3]
    assert len(PdfReader(io.BytesIO(result.data)).pages) == 3


def test_web_image():
    data = web.image(bytearray([128, 64, 32] * 6), 2.0, 3.0)
    response = json.loads(web.read(data))
    assert response["pages"] == [pytest.approx([2 * 72 / 226, 3 * 72 / 226])]
    assert response["annotations"] == 0
