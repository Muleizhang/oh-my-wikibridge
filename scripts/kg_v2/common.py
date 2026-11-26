import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / 'data/local-kg'
VOLUME_ROOTS = (DATA_ROOT, DATA_ROOT / 'vol2', DATA_ROOT / 'vol3')
OUT = Path(os.environ.get('WIKIBRIDGE_KG_DATA', DATA_ROOT)).resolve()
DATABASE_ROOT = Path(os.environ.get('WIKIBRIDGE_KG_DATABASE_ROOT',
                                    Path.home() / '.local/share/cn.wikibridge.desktop')).resolve()
LAYOUT_MODEL_ROOT = Path(os.environ.get('WIKIBRIDGE_LAYOUT_MODELS',
                                       Path.home() / '.paddlex/official_models')).resolve()
DEVELOPMENT_PAGES = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 32, 40, 42, 52, 78, 94, 100]


def selected_pages():
    selection = OUT / 'selection.json'
    return load(selection).get('development_pages', DEVELOPMENT_PAGES) if selection.exists() else DEVELOPMENT_PAGES


def source_path(data_root=OUT):
    path = Path(load(data_root / 'source.json')['path'])
    return path if path.is_absolute() else ROOT / path


def ident(kind, *parts):
    return kind + '-' + hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


def normalized(text):
    indices = [i for i, char in enumerate(text) if not char.isspace()]
    return ''.join(text[i] for i in indices), indices


def evidence(page, start, end, text, bbox=None, block_id=None, engine='tesseract'):
    if not 0 <= start < end <= len(text):
        raise ValueError('Invalid evidence span')
    return {'page': page, 'engine': engine, 'blockId': block_id, 'span': [start, end],
            'text': text[start:end], 'bbox': bbox}
