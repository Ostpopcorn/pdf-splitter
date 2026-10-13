import io
import json
from pathlib import Path

import numpy as np
import pypdfium2
import pytest
from pypdf import PdfReader

from pdfsplitter import Options, image_pdf, jpeg_pdf, split_pdf, split_pdfs, web
from pdfsplitter.image import jpeg_info


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


# JPEG images: 48x32 pixels, light, with a dark block at the top left and a
# red block at the bottom right
DATA = Path(__file__).parent / "data"
LIGHT, DARK, RED = 235, 20, 81  # in gray


def _corner():
    pixels = np.full((32, 48), LIGHT)
    pixels[:16, :24] = DARK
    pixels[16:, 24:] = RED
    return pixels


def _with_orientation(data, orientation):
    """The JPEG image with Exif data that says its orientation."""
    tiff = (b"MM\0*" + (8).to_bytes(4, "big") + (1).to_bytes(2, "big")
            + bytes.fromhex("0112 0003 00000001") + orientation.to_bytes(2, "big")
            + bytes(2) + bytes(4))
    segment = b"Exif\0\0" + tiff
    return (data[:2] + b"\xff\xe1" + (len(segment) + 2).to_bytes(2, "big")
            + segment + data[2:])


# How each orientation shows the image as it is stored
TURNED = {
    1: lambda _a: _a,
    2: np.fliplr,
    3: lambda _a: np.rot90(_a, 2),
    4: np.flipud,
    5: lambda _a: _a.T,
    6: lambda _a: np.rot90(_a, -1),
    7: lambda _a: np.rot90(_a.T, 2),
    8: lambda _a: np.rot90(_a, 1),
}


@pytest.mark.parametrize("orientation", range(1, 9))
@pytest.mark.parametrize("name", ["corner.jpg", "corner-gray.jpg"])
def test_jpeg(name, orientation):
    data = (DATA / name).read_bytes()
    if orientation > 1:
        data = _with_orientation(data, orientation)
    pdf = jpeg_pdf(data, resolution=72)
    image, size = _image(pdf)
    # the image as it is, which PDF readers decode
    assert image["/Filter"] == "/DCTDecode"
    assert image._data == data
    assert image["/ColorSpace"] == ("/DeviceGray" if "gray" in name
                                    else "/DeviceRGB")
    expected = TURNED[orientation](_corner())
    assert size == expected.shape[::-1]
    page = pypdfium2.PdfDocument(pdf)[0]
    rendered = page.render(scale=1, grayscale=True).to_numpy().astype(int)
    assert rendered.shape == expected.shape
    # away from the edges of the blocks, which JPEG blurs
    window = np.lib.stride_tricks.sliding_window_view(
        np.pad(expected, 2, mode="edge"), (5, 5))
    inside = window.min(axis=(2, 3)) == window.max(axis=(2, 3))
    assert inside.sum() > expected.size / 3
    assert np.abs(rendered - expected)[inside].max() < 25


def test_jpeg_info():
    data = (DATA / "corner.jpg").read_bytes()
    assert jpeg_info(data) == (48, 32, 3, 1)
    assert jpeg_info(_with_orientation(data, 6)) == (48, 32, 3, 6)
    # a progressive JPEG image
    frame = data.index(b"\xff\xc0")
    assert jpeg_info(data[:frame + 1] + b"\xc2" + data[frame + 2:])[:2] == (48, 32)


@pytest.mark.parametrize("change, error", [
    (lambda _d: b"\x89PNG" + _d[4:], "It is not a JPEG image"),
    # CMYK, which the browser decodes instead
    (lambda _d: _d.replace(b"\x00\x20\x00\x30\x03", b"\x00\x20\x00\x30\x04"),
     "not in RGB or gray"),
    # arithmetic coding
    (lambda _d: _d.replace(b"\xff\xc0", b"\xff\xc9"), "rare"),
    (lambda _d: _d[:20], "Could not read"),
])
def test_jpeg_error(change, error):
    with pytest.raises(ValueError, match=error):
        jpeg_pdf(change((DATA / "corner.jpg").read_bytes()))


def test_split_pdfs(tall_pdf):
    photo = jpeg_pdf(_with_orientation((DATA / "corner.jpg").read_bytes(), 6))
    result = split_pdfs([tall_pdf, PdfReader(io.BytesIO(photo))],
                        Options(shrink=0))
    assert [len(_layout.slices) for _layout in result.layouts] == [1, 3, 2]
    assert (result.layouts[2].width, result.layouts[2].height) \
        == pytest.approx((32 * 72 / 226, 48 * 72 / 226))
    assert len(PdfReader(io.BytesIO(result.data)).pages) == result.pages == 6


def test_web_jpeg_and_split(tall_pdf):
    photo = web.jpeg((DATA / "corner.jpg").read_bytes())
    data = web.split([tall_pdf, photo],
                     json.dumps({"options": {"paper": "a4", "shrink": 0}}))
    assert len(PdfReader(io.BytesIO(data)).pages) == 1 + 3 + 1
