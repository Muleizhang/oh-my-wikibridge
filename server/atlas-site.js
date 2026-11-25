import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// Accept either the site itself or the directory produced by unzipping a share.
export function resolveAtlasSite(directory) {
  const base = resolve(directory);
  return [base, resolve(base, 'site'), resolve(base, 'wikibridge-three-volumes/site')]
    .find(path => existsSync(resolve(path, 'manifest.json')))
    || base;
}

export function defaultAtlasSite(root) {
  return ['data/local-kg/merged/site', 'data/local-kg/share/wikibridge-three-volumes/site',
    'data/local-kg/atlas-100/site']
    .map(path => resolve(root, path))
    .find(path => existsSync(resolve(path, 'manifest.json')))
    || resolve(root, 'data/local-kg/merged/site');
}
