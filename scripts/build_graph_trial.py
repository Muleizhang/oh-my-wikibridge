"""Build the standalone graph stress-test page without the book or third-party packages."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inline_module(name):
    source = (ROOT / 'src' / name).read_text()
    return '\n'.join(line for line in source.splitlines() if not line.startswith('import ')).replace('export ', '')


def build_graph_trial(output):
    template = (ROOT / 'scripts/graph_trial.html').read_text()
    script = '\n'.join(inline_module(name) for name in ('edge-depth.js', 'spatial-graph.js', 'graph-trial.js'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('__STYLE__', (ROOT / 'src/folio.css').read_text()).replace('__SCRIPT__', script))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build_graph_trial(parser.parse_args().output)
