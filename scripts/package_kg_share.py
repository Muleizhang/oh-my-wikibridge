#!/usr/bin/env python3
"""Package only the current atlas, its referenced images, and selected graphs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'wikibridge-three-volumes/'
URL_FIELDS = {'previewUrl', 'imageUrl', 'detailUrl', 'captionUrl'}

LAUNCHER = '''from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import webbrowser

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=1423)
parser.add_argument('--no-open', action='store_true')
args = parser.parse_args()
directory = Path(__file__).resolve().parent / 'site'
handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
try:
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
except OSError:
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
url = f'http://127.0.0.1:{server.server_port}/'
print('Open:', url, '\\nPress Ctrl+C to stop.', flush=True)
if not args.no_open:
    webbrowser.open(url)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
'''


def asset_urls(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in URL_FIELDS and isinstance(child, str) and child:
                yield child
            yield from asset_urls(child)
    elif isinstance(value, list):
        for child in value:
            yield from asset_urls(child)


def original_pages(manifest, graphs):
    """Relink page/proof images to unchanged originals; keep atlas thumbnails separate."""
    volumes = manifest.get('volumes', [])
    if len(volumes) != len(graphs):
        raise ValueError('Each atlas volume needs its matching graph directory')
    by_label = {volume['label']: (index, volume, path.parent)
                for index, (volume, path) in enumerate(zip(volumes, graphs), 1)}
    sources, replacements, indexes = {}, {}, {}
    for label, (index, volume, root) in by_label.items():
        image_manifest = json.loads((root / 'page-images.json').read_text())
        indexes[label] = {'volume': label, 'pages': {}, 'source': Path(image_manifest.get('source', '')).name}
        image_root = (root / 'images').resolve()
        prefix = volume['prefix']
        if not re.fullmatch(r'[\w-]+', prefix):
            raise ValueError('Invalid volume prefix')
        for page in (p for p in manifest['pages'] if p.get('volume') == label):
            number = page['volumePage']
            record = image_manifest['pages'][str(number)]
            source = (image_root / record['file']).resolve()
            if not source.is_relative_to(image_root) or not source.is_file():
                raise ValueError(f'Missing original page: {label}, {number}')
            if source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                raise ValueError('Unexpected original image format')
            if hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError(f'Original image changed: {label}, {number}')
            url = f'assets/originals/{prefix}/{source.name}'
            replacements[page['previewUrl']] = url
            sources[url] = source
            page.update(imageWidth=record['width'], imageHeight=record['height'], imageSha256=record['sha256'])
            indexes[label]['pages'][str(number)] = {**record, 'file': '../site/' + url}
    def relink(value):
        if isinstance(value, dict):
            # The primary plate and proof use originals; the star map still loads small sprites.
            if value.get('imageUrl') in replacements and not value.get('detailUrl'):
                value['detailUrl'] = value['imageUrl']
            for key, child in list(value.items()):
                if key in {'previewUrl', 'imageUrl', 'captionUrl'} and isinstance(child, str) and child in replacements:
                    value[key] = replacements[child]
                else:
                    relink(child)
        elif isinstance(value, list):
            for child in value:
                relink(child)
    relink(manifest)
    manifest['imageStorage'] = {'mode': 'original_pages', 'pages': len(sources),
                                'originalBytesPreserved': True, 'atlasThumbnailsRetained': True}
    sidecars = [(f'graphs/vol{index}.page-images.json', json.dumps(indexes[label], ensure_ascii=False, indent=2))
                for label, (index, _, _) in by_label.items()]
    return sources, sidecars


def package(site, graphs, output, image_mode='original'):
    site = site.resolve()
    manifest = json.loads((site / 'manifest.json').read_text())
    # A shared artifact needs source names, not the build machine's directory tree.
    for volume in manifest.get('volumes', []):
        if volume.get('source'):
            volume['source'] = Path(volume['source']).name
    originals, sidecars = original_pages(manifest, graphs) if image_mode == 'original' else ({}, [])
    text = json.dumps(manifest, ensure_ascii=False, separators=(',', ':'))
    template = (ROOT / 'scripts/atlas_viewer.html').read_text()
    reasoner = re.sub(r'(?m)^export\s+', '', (ROOT / 'src/kg-reasoner.js').read_text())
    html = template.replace('__REASONER_JS__', reasoner, 1).replace('__MANIFEST_JSON__', text.replace('<', '\\u003c'), 1)
    assets = []
    for url in sorted(set(asset_urls(manifest))):
        source = originals.get(url, (site / url).resolve())
        if (url not in originals and not source.is_relative_to(site)) or not source.is_file():
            raise ValueError(f'Missing or external atlas asset: {url}')
        if source.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
            raise ValueError(f'Unexpected atlas asset type: {url}')
        assets.append((url, source))
    selected_graphs = []
    for index, path in enumerate(graphs, 1):
        graph = json.loads(path.read_text())
        selected_graphs.append((f'graphs/vol{index}.graph.json', path, {
            'volume': index, 'pages': len(graph['selection']),
            'records': len(graph['records']), 'entities': len(graph['entities']),
            'assertions': len(graph['assertions']), 'runId': graph['runId'],
        }))
    readme = f'''# 中国纹样全集 · 三册知识图谱分享包

三册共 {len(manifest['pages'])} 页；星图展示 {len(manifest['items'])} 条图录、{len(manifest['rows'])} 条候选关系。

## 打开图谱

先完整解压 ZIP，需要 Python 3。
- Windows：双击「启动预览.bat」。
- macOS / Linux：在解压目录运行 `sh start-viewer.sh`。
- 也可以运行 `python start-viewer.py`（部分系统用 python3）。浏览器将自动打开本机地址。
- 关闭服务：在启动窗口按 Ctrl+C。

历史长河、2D/3D 星图、原页核读和「符号推演」均在本地运行，不需要 API key。
当前分享包未附大模型服务。使用 DeepSeek Agent 需另行克隆项目、配置自己的密钥并启动统一服务。
主图有聚合显示，点击查看图录列表，放大后展开；未标注时代的记录从「时代待定」入口查看。

## 数据文件

- `site/manifest.json`：跨册统一后的展示图谱。items 为图录条目，rows 为关系，evidence 为出处，pages 保留册数及原 PDF 页码。同名同类型概念统一，图录条目各自独立。
- `graphs/vol1.graph.json`、`vol2.graph.json`、`vol3.graph.json`：各册当前完整候选结果，含属性、尺寸、事件、开放关系、实体提及及对齐建议等未全部绘入星图的数据。三册原生 JSON 请分别读取，不要直接拼接数组。
- `site/assets/`：{'1240 页原尺寸页图完整保留，直接复制源图片字节，不缩放、不重新编码。原页、图录详情及证据引用使用原图；星图另用小预览加速加载。graphs/volN.page-images.json 提供各册原图路径、尺寸及 SHA-256。' if image_mode == 'original' else '1240 页的压缩预览，供展示、对照出处，不附原分辨率图片。'}分享包不附原始 PDF。
- `share-info.json`：各册页数、图录数、候选陈述数及运行标识。

全部数据仍是机器抽取候选，尚未经过独立人工验收；共享纹样或关联路径本身不能证明历史传承。

## 使用项目代码继续开发

仓库：https://github.com/Muleizhang/oh-my-wikibridge
使用 Node.js 24，在项目目录运行：

```bash
node --use-env-proxy server/atlas-server.ts --port 1423 --site /你的解压目录/wikibridge-three-volumes/site
```

如需大模型推理，在该仓库本地 `.env.local` 配置自己的 OpenRouter / DeepSeek 密钥；不要把个人配置加入分享包。
'''
    windows = '@echo off\r\ncd /d "%~dp0"\r\nwhere py >nul 2>&1\r\nif %errorlevel%==0 (\r\n  py -3 start-viewer.py\r\n) else (\r\n  python start-viewer.py\r\n)\r\npause\r\n'
    shell = '#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nif command -v python3 >/dev/null 2>&1; then\n  exec python3 start-viewer.py "$@"\nelse\n  exec python start-viewer.py "$@"\nfi\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in [('README-使用说明.md', readme), ('启动预览.bat', windows),
                           ('start-viewer.sh', shell), ('start-viewer.py', LAUNCHER),
                           ('site/index.html', html), ('site/manifest.json', text),
                           ('share-info.json', json.dumps({'summary': manifest.get('summary'),
                            'imageMode': image_mode, 'originalPages': len(originals),
                            'status': 'unreviewed_candidates', 'graphs': [row[2] for row in selected_graphs]}, ensure_ascii=False, indent=2))]:
            archive.writestr(PREFIX + name, data)
        for name, data in sidecars:
            archive.writestr(PREFIX + name, data)
        for url, source in assets:
            archive.write(source, PREFIX + 'site/' + url)
        for name, path, _ in selected_graphs:
            archive.write(path, PREFIX + name)
    print(json.dumps({'archive': str(output), 'megabytes': round(output.stat().st_size / 1e6, 1),
                      'imageMode': image_mode, 'originalPages': len(originals),
                      'assets': len(assets), 'graphs': [row[2] for row in selected_graphs]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'data/local-kg/merged/site')
    parser.add_argument('--graphs', type=Path, nargs='+', default=[ROOT / 'data/local-kg/graph.json',
                        ROOT / 'data/local-kg/vol2/graph.json', ROOT / 'data/local-kg/vol3/graph.json'])
    parser.add_argument('--image-mode', choices=['original', 'preview'], default='original')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / ('data/local-kg/share/wikibridge-three-volumes-original-pages.zip'
                                   if args.image_mode == 'original' else 'data/local-kg/share/wikibridge-three-volumes.zip')
    package(args.site, args.graphs, output, args.image_mode)
