"""Build styled HWPX documents that follow the project document style guide.

Style guide (docs/tools/README in commit message): title 20pt bold, H1 15pt bold (160%, after 10pt),
H2 12.5pt bold (before 8pt, after 4pt), H3 11pt bold, body 10pt (160%, after 4pt), caption 9pt italic gray (130%),
bullets after 2.5pt, table cell padding 2.0mm (top/bottom) x 2.75mm (left/right), header cells centered on the
primary color, long text left, short values centered, numbers right, tables fit the text width exactly.
Font: 맑은 고딕. Colors: one primary (#1F5C45) + dark gray body (#222222).

usage: python build_hwpx.py BLANK.hwpx OUT.hwpx  (content module passed via build(blocks, ...))
"""
import re
import zipfile
from xml.sax.saxutils import escape

PRIMARY, BODY, MUTED, LINE, LABEL_BG = '#1F5C45', '#222222', '#6B7280', '#B9C5BD', '#EEF3EF'
PT = 100                     # HWPUNIT per point
MM = 283.465                 # HWPUNIT per millimetre
PAD_V, PAD_H = round(2.0 * MM), round(2.75 * MM)

# charPr: (size pt, color, bold, italic)
CHARS = [(10, BODY, 0, 0), (20, PRIMARY, 1, 0), (15, PRIMARY, 1, 0), (12.5, BODY, 1, 0), (11, BODY, 1, 0),
         (9, MUTED, 0, 1), (9.5, '#FFFFFF', 1, 0), (9.5, BODY, 0, 0), (9.5, BODY, 1, 0), (9, MUTED, 0, 0)]
C_BODY, C_TITLE, C_H1, C_H2, C_H3, C_CAP, C_TH, C_TD, C_TL, C_SUB = range(10)
# paraPr: (align, line %, before pt, after pt, left indent pt, first-line indent pt)
PARAS = [('JUSTIFY', 160, 0, 4, 0, 0), ('CENTER', 160, 0, 4, 0, 0), ('LEFT', 160, 14, 10, 0, 0), ('LEFT', 160, 8, 4, 0, 0),
         ('LEFT', 160, 4, 2, 0, 0), ('LEFT', 130, 2, 4, 0, 0), ('LEFT', 160, 0, 2.5, 12, -9), ('CENTER', 150, 0, 0, 0, 0),
         ('LEFT', 150, 0, 0, 0, 0), ('RIGHT', 150, 0, 0, 0, 0), ('LEFT', 100, 2, 8, 0, 0), ('CENTER', 130, 0, 10, 0, 0)]
P_BODY, P_TITLE, P_H1, P_H2, P_H3, P_CAP, P_BULLET, P_TC, P_TLEFT, P_TR, P_TABLE, P_SUB = range(12)
# borderFill ids appended after the 2 originals: 3 cell, 4 header cell, 5 label cell
FILLS = [('SOLID', 'none'), ('SOLID', PRIMARY), ('SOLID', LABEL_BG)]
B_CELL, B_HEAD, B_LABEL = 3, 4, 5


def _char(i, size, color, bold, italic):
    style = ('<hh:italic/>' if italic else '') + ('<hh:bold/>' if bold else '')
    return (f'<hh:charPr id="{i}" height="{round(size * PT)}" textColor="{color}" shadeColor="none" useFontSpace="0" useKerning="0" '
            'symMark="NONE" borderFillIDRef="2"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
            '<hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
            '<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>'
            '<hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>'
            f'<hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>{style}'
            '<hh:strikeout shape="3D" color="#000000"/></hh:charPr>')


def _para(i, align, line, before, after, left, first):
    return (f'<hh:paraPr id="{i}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0">'
            f'<hh:align horizontal="{align}" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>'
            '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="1" keepWithNext="'
            f'{1 if i in (P_H1, P_H2, P_H3) else 0}" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
            f'<hh:margin><hc:intent value="{round(first * PT)}" unit="HWPUNIT"/><hc:left value="{round(left * PT)}" unit="HWPUNIT"/>'
            f'<hc:right value="0" unit="HWPUNIT"/><hc:prev value="{round(before * PT)}" unit="HWPUNIT"/><hc:next value="{round(after * PT)}" unit="HWPUNIT"/></hh:margin>'
            f'<hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>'
            '<hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/></hh:paraPr>')


def _fill(i, kind, face):
    b = f'type="{kind}" width="0.12 mm" color="{LINE}"'
    brush = '' if face == 'none' else f'<hc:fillBrush><hc:winBrush faceColor="{face}" hatchColor="#999999" alpha="0"/></hc:fillBrush>'
    return (f'<hh:borderFill id="{i}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"><hh:slash type="NONE" Crooked="0" isCounter="0"/>'
            f'<hh:backSlash type="NONE" Crooked="0" isCounter="0"/><hh:leftBorder {b}/><hh:rightBorder {b}/><hh:topBorder {b}/><hh:bottomBorder {b}/>'
            f'<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{brush}</hh:borderFill>')


def header(xml):
    chars = ''.join(_char(i, *c) for i, c in enumerate(CHARS))
    paras = ''.join(_para(i, *p) for i, p in enumerate(PARAS))
    xml = re.sub(r'<hh:charProperties itemCnt="\d+">.*?</hh:charProperties>', f'<hh:charProperties itemCnt="{len(CHARS)}">{chars}</hh:charProperties>', xml, flags=re.S)
    xml = re.sub(r'<hh:paraProperties itemCnt="\d+">.*?</hh:paraProperties>', f'<hh:paraProperties itemCnt="{len(PARAS)}">{paras}</hh:paraProperties>', xml, flags=re.S)
    m = re.search(r'<hh:borderFills itemCnt="(\d+)">(.*?)</hh:borderFills>', xml, re.S)
    keep = ''.join(re.findall(r'<hh:borderFill id="[12]".*?</hh:borderFill>', m[2], re.S))
    fills = keep + ''.join(_fill(3 + i, *f) for i, f in enumerate(FILLS))
    return xml[:m.start()] + f'<hh:borderFills itemCnt="{2 + len(FILLS)}">{fills}</hh:borderFills>' + xml[m.end():]


def p(text, para=P_BODY, char=C_BODY):
    return (f'<hp:p id="0" paraPrIDRef="{para}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{char}"><hp:t>{escape(text)}</hp:t></hp:run></hp:p>')


NUMERIC = re.compile(r'^[\d,.\s%~×+\-−/]+(kcal|KB|MB|g|초|행|개|건|장|%|px)?$')


def cell_align(text):
    if NUMERIC.match(text.strip()):
        return P_TR
    return P_TC if len(text) <= 10 else P_TLEFT


TABLE_ID = [2000]


def table(rows, widths, width, header_row=True, label_col=True):
    """rows: list of lists of str. widths: relative column weights. width: text-area width (HWPUNIT)."""
    TABLE_ID[0] += 1
    total = sum(widths)
    cols = [round(width * w / total) for w in widths]
    cols[-1] = width - sum(cols[:-1])
    tr = []
    for r, row in enumerate(rows):
        tcs = []
        for c, text in enumerate(row):
            if header_row and r == 0:
                fill, para, char = B_HEAD, P_TC, C_TH
            elif label_col and c == 0:
                fill, para, char = B_LABEL, P_TC, C_TL
            else:
                fill, para, char = B_CELL, cell_align(text), C_TD
            body = ''.join(p(line, para, char) for line in str(text).split('\n'))
            tcs.append(f'<hp:tc name="" header="{1 if header_row and r == 0 else 0}" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{fill}">'
                       '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" '
                       f'textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">{body}</hp:subList>'
                       f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="{cols[c]}" height="1600"/>'
                       f'<hp:cellMargin left="{PAD_H}" right="{PAD_H}" top="{PAD_V}" bottom="{PAD_V}"/></hp:tc>')
        tr.append('<hp:tr>' + ''.join(tcs) + '</hp:tr>')
    return (f'<hp:p id="0" paraPrIDRef="{P_TABLE}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">'
            f'<hp:tbl id="{TABLE_ID[0]}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
            f'pageBreak="CELL" repeatHeader="1" rowCnt="{len(rows)}" colCnt="{len(cols)}" cellSpacing="0" borderFillIDRef="{B_CELL}" noAdjust="0">'
            f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{1600 * len(rows)}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" '
            'vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/><hp:outMargin left="0" right="0" top="0" bottom="1000"/>'
            f'<hp:inMargin left="{PAD_H}" right="{PAD_H}" top="{PAD_V}" bottom="{PAD_V}"/>' + ''.join(tr) + '</hp:tbl></hp:run></hp:p>')


def build(blank, out, blocks):
    """blocks: list of (kind, payload). kinds: sub, title, h1, h2, h3, p, bullets, caption, code, table."""
    with zipfile.ZipFile(blank) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    parts = dict((i.filename, d.decode('utf-8') if i.filename.endswith('.xml') else d) for i, d in items)
    sec = parts['Contents/section0.xml']
    pg = re.search(r'<hp:pagePr [^>]*width="(\d+)"[^>]*>.*?<hp:margin [^>]*left="(\d+)" right="(\d+)"', sec, re.S)
    width = int(pg[1]) - int(pg[2]) - int(pg[3])
    out_xml = []
    for kind, val in blocks:
        if kind == 'sub': out_xml.append(p(val, P_SUB, C_SUB))
        elif kind == 'title': out_xml.append(p(val, P_TITLE, C_TITLE))
        elif kind == 'h1': out_xml.append(p(val, P_H1, C_H1))
        elif kind == 'h2': out_xml.append(p(val, P_H2, C_H2))
        elif kind == 'h3': out_xml.append(p(val, P_H3, C_H3))
        elif kind == 'p': out_xml.append(p(val))
        elif kind == 'caption': out_xml.append(p(val, P_CAP, C_CAP))
        elif kind == 'bullets': out_xml += [p('•  ' + t, P_BULLET) for t in val]
        elif kind == 'code': out_xml.append(table([['\n'.join(val)]], [1], width, header_row=False, label_col=False))
        elif kind == 'table': out_xml.append(table(val['rows'], val.get('widths') or [1] * len(val['rows'][0]), width, val.get('header', True), val.get('label', True)))
    first_end = sec.index('</hp:p>') + len('</hp:p>')           # keep the original section/page settings paragraph
    sec = sec[:first_end] + ''.join(out_xml) + sec[first_end:]
    parts['Contents/section0.xml'] = sec
    parts['Contents/header.xml'] = header(parts['Contents/header.xml'])
    with zipfile.ZipFile(out, 'w') as zo:
        for info, _ in items:
            data = parts[info.filename]
            zo.writestr(info, data.encode('utf-8') if isinstance(data, str) else data,
                        compress_type=zipfile.ZIP_STORED if info.filename == 'mimetype' else zipfile.ZIP_DEFLATED)
    return width
