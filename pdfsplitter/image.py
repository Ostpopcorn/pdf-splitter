"""Put an image on a page of a PDF, e.g., a page of notes that is exported
from a reMarkable as an image, or a photo, so that it is split like a page of
a PDF.

A JPEG image is put in the PDF as it is, which PDF readers can show. Other
images come as pixels, which the browser decoded, so that no library is
needed to read them."""
import io

from pypdf import PdfWriter
from pypdf.generic import (BooleanObject, DecodedStreamObject,
                           DictionaryObject, NameObject, NumberObject)

from .split import _number

# Dots per inch of the image, like the screen of a reMarkable, so that a
# page from a reMarkable is as large as in a PDF from it. Only the shape of a
# page matters for the split, which scales it to the width of the paper.
RESOLUTION = 226

# The matrices that place the image, as it is stored, on a page of the width
# w and the height h, turned and flipped like the Exif orientation says.
# Orientations 5 to 8 turn the image by a quarter, so that w is its height.
_ORIENTATIONS = {
    1: lambda w, h: (w, 0, 0, h, 0, 0),
    2: lambda w, h: (-w, 0, 0, h, w, 0),
    3: lambda w, h: (-w, 0, 0, -h, w, h),
    4: lambda w, h: (w, 0, 0, -h, 0, h),
    5: lambda w, h: (0, -h, -w, 0, w, h),
    6: lambda w, h: (0, -h, w, 0, 0, h),
    7: lambda w, h: (0, h, w, 0, 0, 0),
    8: lambda w, h: (0, h, -w, 0, w, 0),
}

# The start of frames of JPEG images that PDF readers show: baseline,
# extended, and progressive, with Huffman coding
_FRAMES = (0xC0, 0xC1, 0xC2)
_OTHER_FRAMES = (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)


def _image_pdf(image, width, height, orientation, resolution):
    """A PDF (bytes) with one page that shows the image (a stream) of the
    width and the height in pixels, as the orientation says."""
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(width),
        NameObject("/Height"): NumberObject(height),
        NameObject("/BitsPerComponent"): NumberObject(8),
        # smooth the pixels when the image is shown larger, e.g., printed
        NameObject("/Interpolate"): BooleanObject(True),
    })
    if orientation >= 5:
        width, height = height, width
    page_width = width * 72 / resolution
    page_height = height * 72 / resolution
    writer = PdfWriter()
    page = writer.add_blank_page(page_width, page_height)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({
            NameObject("/Image"): writer._add_object(image)})})
    content = DecodedStreamObject()
    content.set_data("q {} cm /Image Do Q\n".format(" ".join(map(
        _number, _ORIENTATIONS[orientation](page_width, page_height))))
                     .encode())
    page.replace_contents(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


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
    image[NameObject("/ColorSpace")] = NameObject(
        "/DeviceGray" if gray else "/DeviceRGB")
    return _image_pdf(image.flate_encode(), width, height, 1, resolution)


def _exif_orientation(tiff):
    """The orientation (1 to 8) in the Exif data of a JPEG image, which is
    a TIFF header and its first directory, or 1."""
    order = {b"II": "little", b"MM": "big"}.get(tiff[:2])
    if order is None:
        return 1

    def number(position, size):
        return int.from_bytes(tiff[position:position + size], order)

    directory = number(4, 4)
    for _i in range(number(directory, 2)):
        entry = directory + 2 + 12 * _i
        if entry + 12 > len(tiff):
            break
        if number(entry, 2) == 0x0112:
            orientation = number(entry + 8, 2)
            return orientation if orientation in _ORIENTATIONS else 1
    return 1


def jpeg_info(data):
    """Return the width and the height in pixels, the number of colors, and
    the Exif orientation of a JPEG image (bytes), or raise ValueError if PDF
    readers cannot show it as it is."""
    if data[:3] != b"\xff\xd8\xff":
        raise ValueError("It is not a JPEG image")
    position = 2
    orientation = 1
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            break
        marker = data[position + 1]
        if marker == 0xFF:  # fill
            position += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # without a length
            position += 2
            continue
        length = int.from_bytes(data[position + 2:position + 4], "big")
        segment = data[position + 4:position + 2 + length]
        if marker == 0xE1 and segment[:6] == b"Exif\0\0":
            orientation = _exif_orientation(segment[6:])
        elif marker in _FRAMES and len(segment) >= 6:
            height = int.from_bytes(segment[1:3], "big")
            width = int.from_bytes(segment[3:5], "big")
            colors = segment[5]
            if segment[0] != 8 or not width or not height:
                raise ValueError("The JPEG image is not 8 bit")
            return width, height, colors, orientation
        elif marker in _OTHER_FRAMES:
            raise ValueError("The JPEG image is coded in a rare way")
        elif marker == 0xDA:  # the image data, without a frame before it
            break
        position += 2 + length
    raise ValueError("Could not read the JPEG image")


def jpeg_pdf(data, resolution=RESOLUTION):
    """Return a PDF (bytes) with one page that shows a JPEG image (bytes) as
    it is, turned as its Exif orientation says. A JPEG image in CMYK, which
    PDF readers show in different colors, raises ValueError."""
    width, height, colors, orientation = jpeg_info(data)
    if colors not in (1, 3):
        raise ValueError("The JPEG image is not in RGB or gray")
    image = DecodedStreamObject()
    image.set_data(bytes(data))
    image.update({
        NameObject("/Filter"): NameObject("/DCTDecode"),
        NameObject("/ColorSpace"): NameObject(
            "/DeviceGray" if colors == 1 else "/DeviceRGB"),
    })
    return _image_pdf(image, width, height, orientation, resolution)
