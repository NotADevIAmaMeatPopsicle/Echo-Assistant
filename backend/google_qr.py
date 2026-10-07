"""Locally render a short-lived Google consent URL; never send it to a QR service."""
import qrcode
from qrcode.image.svg import SvgPathImage


def svg(url: str) -> bytes:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=4)
    code.add_data(url)
    code.make(fit=True)
    return code.make_image(image_factory=SvgPathImage).to_string(encoding='utf-8')
