"""Private, in-memory conversion between the image formats Dashboard supports."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import cairosvg
from flask import Blueprint, render_template, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename


image_converter = Blueprint("image_converter", __name__, url_prefix="/tools/image-converter")
MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
MAX_BATCH_FILES = 30
Image.MAX_IMAGE_PIXELS = 40_000_000

FORMATS = {
    "avif": {"pillow": "AVIF", "mime": "image/avif", "extension": "avif", "quality": 70},
    "bmp": {"pillow": "BMP", "mime": "image/bmp", "extension": "bmp"},
    "png": {"pillow": "PNG", "mime": "image/png", "extension": "png"},
    "jpeg": {"pillow": "JPEG", "mime": "image/jpeg", "extension": "jpg", "quality": 90},
    "svg": {"mime": "image/svg+xml", "extension": "svg"},
    "tiff": {"pillow": "TIFF", "mime": "image/tiff", "extension": "tiff"},
    "webp": {"pillow": "WEBP", "mime": "image/webp", "extension": "webp", "quality": 85},
}
PILLOW_TO_KEY = {details["pillow"]: key for key, details in FORMATS.items() if "pillow" in details}


def _jpeg_image(image):
    """JPEG has no alpha channel, so composite transparent pixels onto white."""
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _target_image(image, target):
    if target == "jpeg":
        return _jpeg_image(image)
    if image.mode not in {"RGB", "RGBA", "L", "LA"}:
        return image.convert("RGBA" if "transparency" in image.info else "RGB")
    return image


def _is_svg(raw):
    return b"<svg" in raw[:4096].lower()


def _svg_image(raw):
    try:
        rendered = cairosvg.svg2png(bytestring=raw, unsafe=False)
    except Exception as error:
        raise ValueError("Use a valid SVG image.") from error
    return Image.open(BytesIO(rendered))


def _svg_bytes(image):
    png = BytesIO()
    image.save(png, format="PNG")
    import base64
    encoded = base64.b64encode(png.getvalue()).decode("ascii")
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{image.width}" height="{image.height}" viewBox="0 0 {image.width} {image.height}">'
            f'<image width="{image.width}" height="{image.height}" href="data:image/png;base64,{encoded}"/>'
            f'</svg>').encode("utf-8")


def _convert(raw, target):
    source = _svg_image(raw) if _is_svg(raw) else Image.open(BytesIO(raw))
    with source:
        if source.format not in PILLOW_TO_KEY and not _is_svg(raw):
            raise ValueError("Use an AVIF, BMP, PNG, JPEG, SVG, TIFF, or WebP image.")
        source.load()
        image = ImageOps.exif_transpose(source)
        if target == "svg":
            return _svg_bytes(image)
        converted = _target_image(image, target)
        output = BytesIO()
        options = {"format": FORMATS[target]["pillow"]}
        if "quality" in FORMATS[target]:
            options["quality"] = FORMATS[target]["quality"]
        converted.save(output, **options)
        return output.getvalue()


def _download_name(filename, target, used_names):
    stem = Path(secure_filename(filename)).stem or "converted-image"
    extension = FORMATS[target]["extension"]
    candidate, number = f"{stem}.{extension}", 2
    while candidate in used_names:
        candidate = f"{stem}-{number}.{extension}"
        number += 1
    used_names.add(candidate)
    return candidate


@image_converter.route("", methods=["GET", "POST"])
@image_converter.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template("image_converter.html", formats=FORMATS)

    target = str(request.form.get("format") or "").lower()
    uploaded = [item for item in request.files.getlist("images") if item and item.filename]
    if not uploaded and request.files.get("image"):
        uploaded = [request.files["image"]]
    if target not in FORMATS:
        return render_template("image_converter.html", formats=FORMATS, error="Choose an output format."), 400
    if not uploaded:
        return render_template("image_converter.html", formats=FORMATS, error="Choose one or more AVIF, PNG, JPEG, or WebP images."), 400
    if len(uploaded) > MAX_BATCH_FILES:
        return render_template("image_converter.html", formats=FORMATS, error="Choose no more than 30 images at once."), 400

    converted_files, total_bytes, used_names = [], 0, set()
    for item in uploaded:
        raw = item.read(MAX_IMAGE_BYTES + 1)
        total_bytes += len(raw)
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            return render_template("image_converter.html", formats=FORMATS, error=f"{item.filename} must be smaller than 30 MB."), 400
        if total_bytes > MAX_BATCH_BYTES:
            return render_template("image_converter.html", formats=FORMATS, error="The total upload size must be smaller than 100 MB."), 400
        try:
            converted_files.append((_download_name(item.filename, target, used_names), _convert(raw, target)))
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
            message = str(error) if isinstance(error, ValueError) else "could not be converted"
            return render_template("image_converter.html", formats=FORMATS, error=f"{item.filename}: {message}"), 400

    if len(converted_files) == 1:
        filename, content = converted_files[0]
        return send_file(BytesIO(content), mimetype=FORMATS[target]["mime"], as_attachment=True, download_name=filename)

    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for filename, content in converted_files:
            bundle.writestr(filename, content)
    archive.seek(0)
    return send_file(archive, mimetype="application/zip", as_attachment=True, download_name="converted-images.zip")


def init_image_converter(app):
    app.register_blueprint(image_converter)
