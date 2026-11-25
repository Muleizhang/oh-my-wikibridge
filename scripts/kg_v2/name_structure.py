"""Split source catalog names into typed slots without changing their wording."""
import re

VERSION = 'catalog-structure-v1'
TECHNIQUES = ('金银平脱', '蚌片镶嵌', '刻纹', '刻划', '刻画', '印纹', '彩绘', '镂孔',
              '镂空', '透雕', '浮雕', '圆雕', '阴刻', '阳刻', '铸造', '模印', '压印',
              '印花', '刻花', '刺绣', '织造', '镶嵌', '鎏金', '镀金', '错金银', '漆绘')
PARTS = {'口沿':'口沿','内壁':'内壁','外壁':'外壁','颈部':'颈部','肩部':'肩部','腹部':'腹部',
         '底部':'底部','镜背':'镜背','盘心':'盘心','器盖':'器盖','壶盖':'壶盖','鼎耳':'鼎耳',
         '尊腹':'腹部','罐肩':'肩部','瓶腹':'腹部','剑柄':'剑柄','刀柄':'刀柄'}
COMPOSITIONS = ('二方连续','四方连续','左右对称','中心对称','放射式','散点式','满地式')
SHAPES = ('象','犀','牛','羊','虎','龙','鸟','鸮','鹿','鱼','龟','人','羽人','兽','伏鸟双尾虎')
QUOTED = re.compile(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"]*"')
PARENS = re.compile(r'\([^)]*\)|（[^）]*）')


def parse_name(record, document):
    from .caption_fields import MATERIALS, name_lines
    from .artifact_types import TOKENS
    materials = {**MATERIALS, '白玉':'玉','碧玉':'玉','玛瑙':'玛瑙','水晶':'水晶',
                 '玻璃':'玻璃','琥珀':'琥珀','毛':'毛','贝':'贝','铅':'铅','锡':'锡'}
    heads = {**TOKENS, **{x:x for x in ['鉴','鑑','匝','钫','铎','铙','镈','管','珠','牌','瑗','板',
        '锛','凿','铲','锥','针','杖','杖头','佛像','造像','人像','贮贝器','鼓','棺','钉']}}
    lines = list(name_lines(record))
    if not lines:
        a,b = record['titleSpan']; lines=[(a,document['text'][a:b])]
    chars,indices=[],[]
    for base,line in lines:
        if re.fullmatch(r'[\dA-Za-z\W_]+',line): continue
        for i,char in enumerate(line):
            if not char.isspace(): chars.append(char);indices.append(base+i)
    text=''.join(chars)
    if not text or re.search(r'\d+[.．、]',text): return {}
    if '仿' in text: return {}
    clean=QUOTED.sub(lambda m:' '*len(m[0]),text)
    clean=PARENS.sub(lambda m:' '*len(m[0]),clean)
    def field(label,start,end,**extra):
        lo,hi=indices[start],indices[end-1]+1
        return {'label':label,'span':[lo,hi],'raw':document['text'][lo:hi],**extra}
    result={}
    techs=[]; motif_text=list(clean)
    for match in re.finditer('|'.join(sorted(TECHNIQUES,key=len,reverse=True)),clean):
        techs.append(field(match[0],*match.span()))
        motif_text[match.start():match.end()]=' '*len(match[0])
    result['technique']=techs
    # 印纹陶 names a process/material combination, not an extra motif boundary.
    for match in re.finditer('印纹陶',clean):motif_text[match.start():match.end()]=' '*len(match[0])
    last_motif=''.join(motif_text).rfind('纹')
    carrier_matches=[]
    for match in re.finditer('|'.join(re.escape(h) for h in sorted(heads,key=len,reverse=True)),clean):
        if re.match(r'纹|形|式|状|口|腹|肩|颈|足|带纹|线纹|圈纹',clean[match.end():]):continue
        carrier_matches.append(match)
    after=[m for m in carrier_matches if m.start()>last_motif]
    if after:carrier_matches=after
    mat_matches=[]
    for match in re.finditer('|'.join(re.escape(m) for m in sorted(materials,key=len,reverse=True)),clean):
        prefix=clean[:match.start()]
        if any(t['span'][0] <= indices[match.start()] < t['span'][1] for t in techs) and match[0]!='印纹陶':continue
        if prefix and prefix[-1] in '鎏镀错嵌包贴描涂泥洒贮':continue
        if prefix and prefix[-1] in '金银铜铁' and not re.search(r'鎏金$|镀金$|错金银$',prefix):continue
        if after and match.start()<last_motif:continue
        if not carrier_matches and last_motif>=0 and match.start()<last_motif:continue
        # A material after the carrier belongs to the following decoration clause.
        if carrier_matches and match.start()>carrier_matches[-1].end():continue
        mat_matches.append(match)
    if mat_matches:
        # A later explicit material+carrier is the object depicted by earlier motifs.
        values={materials[m[0]] for m in mat_matches}
        if len(values)>1:
            mat_matches=[]
            # An explicit composite surface process is still a technique.
            if not any(t['label']=='金银平脱' for t in techs):return {}
            return {'technique':techs}
        if len(values)==1:
            mat=mat_matches[-1]
            result['material']=[field(materials[mat[0]],*mat.span())]
            plausible=[h for h in carrier_matches if h.start()>=mat.start()]
            if plausible:carrier_matches=plausible
            else:carrier_matches=[]
            if not carrier_matches and len(mat[0])==1:
                suffix=clean[mat.end():].strip()
                if suffix and suffix not in SHAPES and suffix not in {'残片','片'}:
                    result.pop('material',None)
                    return {k:v for k,v in result.items() if v}
            # Pure material/zoomorphic titles still support a broad carrier class.
            broad={'玉':'玉器','铜':'铜器','青铜':'铜器','陶':'陶器','瓷':'瓷器','骨':'骨器',
                   '石':'石器','金':'金器','银':'银器','牙':'牙器','象牙':'牙器','木':'木器'}
            if not carrier_matches and materials[mat[0]] in broad:
                result['artifact_type']=[field(broad[materials[mat[0]]],*mat.span(),specificity='broad')]
            shape_end=carrier_matches[-1].start() if carrier_matches else len(clean)
            gap=clean[mat.end():shape_end].strip()
            if gap in SHAPES:
                start=clean.find(gap,mat.end())
                result['shape']=[field(gap+'形',start,start+len(gap))]
    else:
        # Compound carrier names explicitly encode their material.
        for raw,label in [('画像石','石'),('石刻','石')]:
            match=re.search(raw,clean)
            if match:
                start=match.start()+raw.index('石')
                result['material']=[field(label,start,start+1)];break
    if carrier_matches:
        head=carrier_matches[-1]
        result['artifact_type']=[field(heads[head[0]],*head.span(),specificity='explicit')]
    for kind,words in [('decoration_part',PARTS),('composition',COMPOSITIONS)]:
        result[kind]=[field(PARTS[m[0]] if kind=='decoration_part' else m[0],*m.span())
                      for m in re.finditer('|'.join(map(re.escape,sorted(words,key=len,reverse=True))),clean)]
    # Culture names must be in the catalog title, never guessed from its excavation site.
    result['culture']=[field(m[0],*m.span()) for m in re.finditer(
        r'(?:仰韶|马家窑|半坡|庙底沟|龙山|大汶口|良渚|红山|河姆渡|齐家|二里头|大溪|屈家岭|马家浜|崧泽|卡若|昂昂溪|凤鼻头|新开流)文化',clean)]
    result['decoration_material']=[]
    for match in re.finditer(r'(?:鎏|镀|错|嵌|包|贴)(?:金|银)|金箔|银箔|蚌片|蚌泡',text):
        value=match[0]
        # Foils can themselves be the catalog object. Require explicit decoration context.
        if value in {'金箔','银箔','蚌片','蚌泡'} and not re.search(r'镶嵌|平脱|贴|漆|复原图',text):continue
        start=match.start()+1 if value[0] in '鎏镀错嵌包贴' else match.start()
        raw=text[start:match.end()]
        result['decoration_material'].append(field(raw,start,match.end()))
    return {k:v for k,v in result.items() if v}
