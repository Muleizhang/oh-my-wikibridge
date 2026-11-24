"""Share the desktop SQLite schema with the local importer."""
from .common import ROOT


def schema():
    # Use the exact schema maintained by the desktop app, without a second migration copy.
    text = (ROOT / 'src-tauri/src/store.rs').read_text()
    start = text.index('PRAGMA journal_mode=WAL;')
    end = text.index('\n        "))?;', start)
    return text[start:end]
