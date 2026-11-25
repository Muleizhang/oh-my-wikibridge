"""Build the private first-volume atlas from the matching user's scan (Poppler and Pillow)."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'b5b81b330f9b12ef102fbeed95094d54a51476dfce95900ee8afca0cc6298b23'
TITLE = '中国纹样全集 1 · 新石器时代和商·西周·春秋卷'
# Boxes were read on PDF pages scaled to 1050 px high. Coordinates refer
# to independent image, detail and caption regions, never to the nearest OCR line.
PLATES = [
    (4, 4, '花卉纹', '花卉纹彩陶盆', '河南陕县庙底沟出土',
     (69,408,405,625), (99,437,311,535), (177,868,290,908)),
    (7, 2, '花卉纹', '花卉纹彩陶盆', '高15.6厘米、口径26厘米；江苏邳县大墩子出土',
     (62,298,361,512), (114,365,295,465), (490,782,625,843)),
    (5, 1, '旋纹', '旋纹彩陶罐', '右：俯视图；甘肃出土',
     (62,64,361,338), (396,64,687,338), (489,801,650,845)),
    (5, 4, '旋纹', '旋纹双耳彩陶瓶', '高25.4厘米、口径7.2厘米；甘肃兰州杏核台出土',
     (395,373,685,762), (473,508,613,687), (489,940,632,999)),
]


# Visual observations describe only the displayed crop, independently of catalog assertions.
OBSERVATIONS = {
    (4, 4): '宽阔的黑彩围出浅色花瓣，花瓣之间可见细线。',
    (7, 2): '红色底上，尖瓣内各有一道深色细线，在中央交会。',
    (5, 1): '从器口上方看，四组旋线环绕中央开口。',
    (5, 4): '瓶腹上的弧线向圆心收拢，圆心内还有一枚深色小点。',
}


def jpg(im, max_side=None):
    im = im.copy()
    if max_side:
        im.thumbnail((max_side, max_side))
    f = io.BytesIO()
    im.convert('RGB').save(f, format='JPEG', quality=87, optimize=True)
    return f.getvalue()


def build(pdf, out):
    with pdf.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != DIGEST:
            raise ValueError('PDF 与标注版本不一致，页码与选区无法复用。')
    out.mkdir(parents=True, exist_ok=True)
    assets = {}

    def asset(name, im, size=None):
        data = jpg(im, size)
        (out/name).write_bytes(data)
        assets[name] = 'data:image/jpeg;base64,' + base64.b64encode(data).decode()
        return 'book-sample/' + name

    pages = {}
    with TemporaryDirectory() as temp:
        for p in (3, 4, 5, 7):
            prefix = str(Path(temp)/str(p))
            subprocess.run(['pdftoppm', '-f', str(p), '-l', str(p), '-singlefile', '-scale-to', '2100',
                            '-jpeg', str(pdf), prefix], check=True)
            with Image.open(prefix + '.jpg') as im:
                pages[p] = im.copy()
            asset(f'p{p}.jpg', pages[p], 1200)
    rows, evidence = [], []
    header = (18,106,248,165)  # coordinates on the 2100 px-high PDF page 3
    asset('section.jpg', pages[3].crop(header))
    for page, item, motif, artifact, note, plate, detail, caption in PLATES:
        src = pages[page]
        def region(name, rect):
            return asset(f'p{page}-{item}-{name}.jpg', src.crop(tuple(2*v for v in rect)), 830)
        def normalized(rect):
            return [round(2*v/src.size[i%2], 6) for i,v in enumerate(rect)]
        key = f'book1:{page}:{item}'
        locator = f'PDF 第 {page} 页 · 书内图版第 {page-2} 页 · 图 {item}'
        quote = f'{item}. {artifact}。{note}。'
        caption_image = region('caption', caption)
        figure = region('artifact', plate)
        closeup = region('detail', detail)
        evidence.append(dict(id=key, sourceId='book-first-volume', corpusId='book-first-volume',
            corpusName='原书图版核读样本', sourceName=TITLE, extension='pdf', bytes=pdf.stat().st_size,
            sha256=DIGEST, kind='page', ordinal=page, locator=locator, text=quote, method='scan_read',
            confidence=None, previewUrl=f'book-sample/p{page}.jpg', captionUrl=caption_image, bbox=normalized(caption)))
        attrs = [('decorated_with', motif, key, quote), ('made_of', '陶', key, quote),
                 ('period', '新石器时代', 'book1:section', '图版分期：新石器时代。')]
        for pred, obj, evid, text in attrs:
            rows.append(dict(id=key+':'+pred, artifactId=key, sourceId='book-first-volume', sourceName=TITLE,
                bytes=pdf.stat().st_size, artifact=artifact, item=item, page=page, locator=locator,
                proofLocator='PDF 第 3 页 · 图版分期标题' if pred == 'period' else locator,
                predicate=pred, objectId='book1:'+pred+':'+obj, object=obj, quote=text, evidenceId=evid,
                qualifiers=[{'text':'据图版分期'}] if pred=='period' else [], regions=None,
                regionBoxes={'artifact': normalized(plate), 'motif': normalized(detail), 'caption': normalized(caption)},
                imageUrl=figure, detailUrl=closeup, captionUrl=caption_image,
                findspot=note.split('；')[-1].removesuffix('出土'), observation=OBSERVATIONS[(page,item)],
                detailLabel='俯视图' if (page,item)==(5,1) else '纹样局部'))
    evidence.append({**evidence[0], 'id':'book1:section','ordinal':3,'locator':'PDF 第 3 页 · 图版分期标题',
        'previewUrl':'book-sample/p3.jpg','captionUrl':'book-sample/section.jpg','text':'新石器时代',
        'bbox':[v/pages[3].size[i%2] for i,v in enumerate(header)]})
    manifest = {'title':TITLE,'sha256':DIGEST,'rows':rows,'evidence':evidence}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    template = (ROOT/'scripts/book_atlas.html').read_text()
    inline = json.dumps(dict(manifest=manifest,images=assets),ensure_ascii=False).replace('<','\\u003c')
    geometry = (ROOT/'src/edge-depth.js').read_text().replace('export ', '')
    spatial = (ROOT/'src/spatial-graph.js').read_text().split('\n', 1)[1].replace('export function', 'function', 1)
    network = (ROOT/'src/motif-network.js').read_text().split('\n', 1)[1].replace('export function','function',1)
    (out/'index.html').write_text(template.replace('__FOLIO_CSS__',(ROOT/'src/folio.css').read_text()).replace('__BOOK_DATA__',inline).replace('__DRAW_NETWORK__','\n'.join((geometry, spatial, network))))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'public/book-sample')
    args = parser.parse_args()
    m = build(args.pdf,args.output)
    print(f"{len(m['rows'])} 条陈述，{len(PLATES)} 个图版条目。{args.output/'index.html'}")
