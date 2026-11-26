"""Build the standalone atlas from the same template and reasoner as the server."""
import re

from .common import ROOT

TEMPLATE = ROOT / 'scripts/atlas_viewer.html'
REASONER_JS = ROOT / 'src/kg-reasoner.js'


def render_atlas(manifest_json):
    template = TEMPLATE.read_text(encoding='utf-8')
    reasoner = re.sub(r'(?m)^export\s+', '', REASONER_JS.read_text(encoding='utf-8'))
    return template.replace('__REASONER_JS__', reasoner, 1).replace(
        '__MANIFEST_JSON__', manifest_json.replace('<', '\\u003c'), 1)
