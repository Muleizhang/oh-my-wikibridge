"""Keep original PDF image streams; generate OCR rasters only temporarily."""
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .common import OUT, ident, load, save, source_path


def render_ocr_image(source, page_number, width):
    import fitz
    from PIL import Image, ImageOps
    with fitz.open(source) as document:
        page = document[page_number - 1]
        scale = width / page.rect.width
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    return ImageOps.autocontrast(Image.frombytes('L', [pixmap.width, pixmap.height], pixmap.samples), cutoff=0.5)


@contextmanager
def ocr_image_file(source, page_number, width):
    image = render_ocr_image(source, page_number, width)
    with tempfile.TemporaryDirectory(prefix='wikibridge-ocr-') as directory:
        target = Path(directory) / f'page-{page_number}.png'
        image.save(target)
        yield target, image.size


def layout_input_signature(record):
    return ident('ocr-input', record['source'], record['source_signature'],
                 record['render_width'], 'grayscale-autocontrast-0.5-v1')


def extract_page_image(document, page_number, render_width, directory):
    """Extract a single full-page image without re-encoding JPEG bytes.

    Refuse unsupported page compositions instead of dropping vector/text content.
    """
    page = document[page_number - 1]
    images = page.get_images(full=True)
    if len(images) != 1 or page.rotation or page.get_text().strip() or page.get_drawings():
        raise ValueError(f'Page {page_number} is not a single unrotated scan')
    info = images[0]
    if info[1]: raise ValueError(f'Page {page_number} has an image mask')
    bounds, transform = page.get_image_bbox(info, transform=True)
    if (abs(transform.b) > 1e-5 or abs(transform.c) > 1e-5 or transform.a <= 0 or transform.d <= 0
            or any(abs(a-b) > .02 for a,b in zip(bounds, page.rect))):
        raise ValueError(f'Page {page_number} image does not cover the page')
    if info[8] == 'DCTDecode' and document.xref_get_key(info[0], 'Decode')[0] == 'null':
        content = document.xref_stream_raw(info[0]); extension = 'jpg'; mode = 'original_jpeg_stream'
        if not content.startswith(b'\xff\xd8'): raise ValueError('Expected original JPEG stream')
    else:
        extracted = document.extract_image(info[0])
        extension, content = extracted['ext'], extracted['image']; mode = 'original_resolution_lossless'
        if extension not in {'png', 'jpg', 'jpeg'}: raise ValueError(f'Unsupported image: {extension}')
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    filename = f'v1-p{page_number:04d}.source.{extension}'
    destination = directory / filename
    digest = hashlib.sha256(content).hexdigest()
    if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        temporary = destination.with_suffix(destination.suffix + '.tmp')
        temporary.write_bytes(content); temporary.replace(destination)
    scale = render_width / page.rect.width
    return {'page': page_number, 'file': filename, 'mimeType': 'image/jpeg' if extension in {'jpg','jpeg'} else 'image/png',
            'width': info[2], 'height': info[3], 'bytes': len(content), 'sha256': digest, 'storage': mode,
            'ocrViewBox': [bounds.x0*scale, bounds.y0*scale, bounds.width*scale, bounds.height*scale]}


def preview_images():
    manifest = OUT / 'page-images.json'
    return load(manifest)['pages'] if manifest.exists() else {}


def install_previews(graph, application_root):
    """Desktop shares the same image inode when paths are on one filesystem."""
    import shutil
    assets = preview_images()
    if any(str(page) not in assets for page in graph['selection']):
        raise ValueError('Prepare original page images before importing the graph')
    target_dir = Path(application_root) / 'pipeline-pages'; target_dir.mkdir(parents=True, exist_ok=True)
    for page in graph['selection']:
        asset = assets[str(page)]; source = OUT / 'images' / asset['file']; target = target_dir / asset['file']
        if target.exists() and os.path.samefile(source, target): continue
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.unlink(missing_ok=True)
        try: os.link(source, temporary)
        except OSError: shutil.copyfile(source, temporary)
        temporary.replace(target)
    save(target_dir / 'page-images.json', {'pages': assets})
    graph['pageImages'] = {str(page): assets[str(page)] for page in graph['selection']}
