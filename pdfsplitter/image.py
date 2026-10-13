"""Put an image on a page of a PDF, e.g., a page of notes that is exported
from a reMarkable as a PNG image, so that it is split like a page of a PDF.

The pixels come decoded, e.g., by the browser, so that no library is needed
to read the image."""
import io

from pypdf import PdfWriter
from pypdf.generic import (BooleanObject, DecodedStreamObject,
                           DictionaryObject, NameObject, NumberObject)

from .split import _number

# Dots per inch of the image, like the screen of a reMarkable, so that a
# page from a reMarkable is as large as in a PDF from it. Only the shape of a
# page matters for the split, which scales it to the width of the paper.
RESOLUTION = 226


def image_pdf(pixels, width, height, resolution=RESOLUTION):
    """Return a PDF (bytes) with one page that shows an image of the width
    and the height in pixels. The pixels are RGB, three bytes each, row by
    row from the top left. An image in shades of gray is stored as gray."""
    pixels = bytes(pixels)
    if width <= 0 or height <= 0 or len(pixels) != width * height * 3:
        raise ValueError("The pixels do not match the size of the image")
    red = pixels[0::3]
    gray = red == pixels[1::3] == pixels[2::3]
    image = DecodedStreamObject()
    image.set_data(red if gray else pixels)
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(width),
        NameObject("/Height"): NumberObject(height),
        NameObject("/ColorSpace"): NameObject(
            "/DeviceGray" if gray else "/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
        # smooth the pixels when the image is shown larger, e.g., printed
        NameObject("/Interpolate"): BooleanObject(True),
    })
    page_width = width * 72 / resolution
    page_height = height * 72 / resolution
    writer = PdfWriter()
    page = writer.add_blank_page(page_width, page_height)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({
            NameObject("/Image"): writer._add_object(image.flate_encode())})})
    content = DecodedStreamObject()
    content.set_data("q {} 0 0 {} 0 0 cm /Image Do Q\n".format(
        _number(page_width), _number(page_height)).encode())
    page.replace_contents(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
