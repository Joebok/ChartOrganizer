from __future__ import annotations

from pypdf import Transformation
from pypdf.generic import RectangleObject

# PDF dimensions are in points (72 per inch), matching the screen at 300 dpi.
KINDLE_WIDTH = 1680 * 72 / 300
KINDLE_HEIGHT = 1264 * 72 / 300
_INK = bytes(1 if value < 245 else 0 for value in range(256))
_PADDING = 1.0  # PDF point; protects fine strokes at the detected boundary.


def _content_bounds(rendered_page) -> tuple[float, float, float, float]:
    width, height = rendered_page.get_size()
    # Detect scanned images and vector notation alike, without rasterizing output.
    bitmap = rendered_page.render(scale=min(300 / 72, 4096 / max(width, height)), grayscale=True)
    try:
        pixels = bytes(bitmap.buffer)
        left, top, right, bottom = bitmap.width, bitmap.height, -1, -1
        for y in range(bitmap.height):
            row = pixels[y * bitmap.stride:y * bitmap.stride + bitmap.width].translate(_INK)
            first = row.find(b"\x01")
            if first >= 0:
                left = min(left, first)
                right = max(right, row.rfind(b"\x01"))
                top = min(top, y)
                bottom = y
        if right < left:  # Blank pages retain their place and fit the screen.
            return 0, 0, width, height
        return (
            max(0, left * width / bitmap.width - _PADDING),
            max(0, height - (bottom + 1) * height / bitmap.height - _PADDING),
            min(width, (right + 1) * width / bitmap.width + _PADDING),
            min(height, height - top * height / bitmap.height + _PADDING),
        )
    finally:
        bitmap.close()


def add_kindle_page(writer, source_page, rendered_page) -> None:
    left, bottom, right, top = _content_bounds(rendered_page)
    # Honor the visible crop and PDF rotation, including nonzero page origins.
    media, crop = source_page.mediabox, source_page.cropbox
    visible = RectangleObject((max(media.left, crop.left), max(media.bottom, crop.bottom),
                               min(media.right, crop.right), min(media.top, crop.top)))
    source_page.cropbox = visible
    rotation = Transformation().rotate(-source_page.rotation)
    corners = [rotation.apply_on(point) for point in (
        visible.lower_left, visible.lower_right, visible.upper_left, visible.upper_right)]
    oriented = rotation.translate(-min(p[0] for p in corners), -min(p[1] for p in corners))
    scale = min(KINDLE_WIDTH / (right - left), KINDLE_HEIGHT / (top - bottom))
    transform = oriented.scale(scale).translate(
        (KINDLE_WIDTH - (right - left) * scale) / 2 - left * scale,
        (KINDLE_HEIGHT - (top - bottom) * scale) / 2 - bottom * scale,
    )
    output_page = writer.add_blank_page(width=KINDLE_WIDTH, height=KINDLE_HEIGHT)
    output_page.merge_transformed_page(source_page, transform)
