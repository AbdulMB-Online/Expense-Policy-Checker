"""Decode receipt uploads into bounded images for vision inference."""

import base64
import math
import warnings
from contextlib import closing
from io import BytesIO
from threading import Lock

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.database.models import Receipt
from backend.services.errors import ServiceError

MAX_PDF_PAGES = 5
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_EDGE = 2000
# PDFium must not be called concurrently from FastAPI worker threads.
PDF_LOCK = Lock()


def image_url(image: Image.Image) -> str:
    """Normalize orientation, transparency and dimensions without keeping metadata."""
    image = ImageOps.exif_transpose(image)
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    output = BytesIO()
    background.save(output, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def receipt_images(receipt: Receipt) -> list[str]:
    if receipt.media_type == "application/pdf":
        try:
            with PDF_LOCK, pdfium.PdfDocument(receipt.contents) as document:
                if not 1 <= len(document) <= MAX_PDF_PAGES:
                    raise ServiceError(422, "Use a receipt PDF with 1 to 5 pages for autofill.")
                images = []
                for index in range(len(document)):
                    with closing(document[index]) as page:
                        width, height = page.get_size()
                        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                            raise ValueError("Invalid page dimensions")
                        scale = min(2, MAX_IMAGE_EDGE / max(width, height))
                        with closing(page.render(scale=scale)) as bitmap:
                            images.append(image_url(bitmap.to_pil()))
                return images
        except (pdfium.PdfiumError, ValueError, OverflowError) as error:
            raise ServiceError(
                422, "This PDF could not be read. Use an unlocked PDF or a receipt photo."
            ) from error
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(receipt.contents)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ServiceError(422, "Use a receipt image smaller than 20 megapixels.")
                image.load()
                return [image_url(image)]
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ServiceError(422, "This image could not be read. Try another PNG or JPEG.") from error
