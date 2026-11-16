"""Sticker (PDF auf A4, zwei Exemplare) und iPhone-Wallpaper (PNG, dunkel, je zwei Tage nebeneinander) aus
auswahl.json. Symbole stehen in festen Spalten: Laden oder Automat | Bäcker oder Imbiss | Tanke | Rad.
Grau (Sticker) bzw. gelber Balken (Wallpaper) nur bei Stopps mit "wichtig", Bett bei "schlaf", Pfeil bei "umweg_m".
Ein unbekanntes iPhone-Modell bricht ab (sonst "iphone_px": [Breite, Höhe] in roadbook.json).

Aufruf: python3.12 -P render.py <roadbook.json> [auswahl.json]
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True  # kein __pycache__ im Skill-Ordner
from model import EMOJI, Route, lade_auswahl, lade_config, pfad, zeiten_quelle  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

DIN = '/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf'
ANC = '/System/Library/Fonts/Avenir Next Condensed.ttc'
EMOJI_FONT = '/System/Library/Fonts/Apple Color Emoji.ttc'
IPHONE = {  # Bildschirmauflösung in Pixeln
    'iPhone 16 Pro': (1206, 2622), 'iPhone 16 Pro Max': (1320, 2868), 'iPhone 16': (1179, 2556),
    'iPhone 16 Plus': (1290, 2796), 'iPhone 15 Pro': (1179, 2556), 'iPhone 15 Pro Max': (1290, 2796),
    'iPhone 15': (1179, 2556), 'iPhone 14 Pro': (1179, 2556), 'iPhone 13': (1170, 2532),
}

cfg = lade_config(sys.argv[1])
if cfg.get('iphone_px'):
    px = cfg['iphone_px']
    if not (isinstance(px, list) and len(px) == 2 and all(isinstance(v, int) and v >= 300 for v in px)):
        sys.exit('iphone_px muss [Breite, Höhe] in Pixeln sein, etwa [1206, 2622]')
    W, H = px
elif cfg['iphone'] in IPHONE:
    W, H = IPHONE[cfg['iphone']]
else:
    sys.exit(f"iPhone-Modell {cfg['iphone']!r} unbekannt, bekannt sind {', '.join(IPHONE)}. Sonst die Auflösung als "
             '"iphone_px": [Breite, Höhe] in roadbook.json eintragen.')
route = Route(cfg)
stopps = lade_auswahl(cfg, route, sys.argv[2] if len(sys.argv) > 2 else None)
OUT = pfad(cfg, 'out')
ICON = pfad(cfg, 'out', 'icons')
if not (ICON / 'schlaf.png').exists():
    try:
        subprocess.run(['node', str(Path(__file__).resolve().parent / 'icons.js'), str(ICON)], check=True)
    except FileNotFoundError:
        sys.exit('node fehlt: Die Symbole brauchen node mit react, react-dom, react-icons und sharp (README des '
                 'service-kits, Voraussetzungen)')
    except subprocess.CalledProcessError as e:
        sys.exit(f'icons.js endete mit Code {e.returncode} (Meldung von node darüber): react, react-dom, react-icons '
                 'und sharp global über NODE_PATH prüfen')
slug = ''.join(c if c.isalnum() else '-' for c in cfg['titel']).strip('-')

for s in stopps:
    sym = {o['symbol'] for o in s['optionen']}
    s['_tag'] = route.stopp_tag(s)  # Feld tag, sonst Schlaf-Stopp am Abend, sonst nach km
    e = route.eta(s['km'], s['_tag'])
    abends = e.strftime('%H:%M') >= cfg['imbiss_ab']
    if 'laden' in sym and 'automat' in sym:
        print(f"Hinweis {s['kurz']}: Laden und Automat, Spalte zeigt den Laden")
    if 'baecker' in sym and 'imbiss' in sym:
        print(f"Hinweis {s['kurz']}: Bäcker und Imbiss, Spalte zeigt {'Imbiss' if abends else 'Bäcker'}")
    s['slots'] = [
        'laden' if 'laden' in sym else ('automat' if 'automat' in sym else None),
        ('imbiss' if abends or 'baecker' not in sym else 'baecker') if {'baecker', 'imbiss'} & sym else None,
        'tanke' if 'tanke' in sym else None,
        'rad' if 'rad' in sym else None,
    ]
    s['rest'] = round(route.total - s['km'])
    s['umweg_m'] = int(s.get('umweg_m') or 0)
    s['haupt'] = bool(s.get('wichtig'))
    s['schlaf'] = bool(s.get('schlaf'))
tage = [(route.tage[i]['tag'], [s for s in stopps if s['_tag'] == i]) for i in range(len(route.tage))]
tage = [(t, rows) for t, rows in tage if rows]
umwege = sorted({s['umweg_m'] for s in stopps if s['umweg_m']})
genutzt = {sl for s in stopps for sl in s['slots'] if sl}

# ---------------------------------------------------------------- Sticker (PDF)
pdfmetrics.registerFont(TTFont('DINC', DIN))
pdfmetrics.registerFont(TTFont('ANC-Demi', ANC, subfontIndex=2))
pdfmetrics.registerFont(TTFont('ANC-Bold', ANC, subfontIndex=0))
SW, SH = cfg['sticker_mm'][0] * mm, cfg['sticker_mm'][1] * mm
M = 1.0 * mm
HEAD, BAND, FOOT = 3.4 * mm, 4.4 * mm, 3.6 * mm
ROW = (SH - 2 * M - HEAD - len(tage) * BAND - FOOT) / len(stopps)
if ROW < 4.4 * mm:
    print(f'WARNUNG: Zeilenhöhe nur {ROW / mm:.1f} mm, für den Sticker Stopps streichen oder zwei Streifen planen')
KM_R, REST_R, NAME_X = 5.4 * mm, 9.3 * mm, 10.4 * mm
SLOT_W, ICO = 2.9 * mm, 2.6 * mm
SLOT_X = SW - M - 4 * SLOT_W


def fit(text, size, maxw, minsize=7.5):
    while size > minsize and pdfmetrics.stringWidth(text, 'DINC', size) > maxw:
        size -= 0.25
    return size


def gesperrt(c, x, y, text, font, size, space):
    t = c.beginText(x, y)
    t.setFont(font, size)
    t.setCharSpace(space)
    t.textOut(text)
    t.setCharSpace(0)  # sonst gilt der Zeichenabstand für alle folgenden Texte der Seite
    c.drawText(t)


def basis(mid, size):
    return mid - 0.37 * size * 0.3528 * mm


def sticker(c, x0, y0):
    c.setLineWidth(0.35)
    c.setStrokeGray(0)
    c.roundRect(x0, y0, SW, SH, 1.8 * mm, stroke=1, fill=0)
    y = y0 + SH - M - HEAD
    c.setFillGray(0.3)
    c.setFont('DINC', 5.6)
    c.drawRightString(x0 + KM_R, y + 0.9 * mm, 'KM')
    c.drawRightString(x0 + REST_R, y + 0.9 * mm, 'REST')
    c.drawRightString(x0 + SW - M - 0.4 * mm, y + 0.9 * mm, cfg['titel'].upper()[:30])
    for tag, rows in tage:
        y -= BAND
        c.setFillGray(0)
        c.rect(x0 + M, y, SW - 2 * M, BAND, stroke=0, fill=1)
        c.setFillGray(1)
        gesperrt(c, x0 + M + 1.2 * mm, y + 1.25 * mm, tag, 'DINC', 8, 1.1)
        for s in rows:
            y -= ROW
            if s['haupt']:
                c.setFillGray(0.85)
                c.rect(x0 + M, y, SW - 2 * M, ROW, stroke=0, fill=1)
            c.setStrokeGray(0.7)
            c.setLineWidth(0.12)
            c.line(x0 + M, y, x0 + SW - M, y)
            c.line(x0 + KM_R + 0.45 * mm, y + 0.9 * mm, x0 + KM_R + 0.45 * mm, y + ROW - 0.9 * mm)
            mid = y + ROW / 2
            c.setFillGray(0)
            c.setFont('DINC', 11)
            c.drawRightString(x0 + KM_R, basis(mid, 11), str(round(s['km'])))
            c.setFillGray(0.32)
            c.setFont('DINC', 8)
            c.drawRightString(x0 + REST_R, basis(mid, 8), str(s['rest']))
            first = next((i for i, v in enumerate(s['slots']) if v), 4)
            extra = 3.0 * mm * (bool(s['umweg_m']) + s['schlaf'])
            size = fit(s['kurz'], 10.5 if s['haupt'] else 10, SLOT_X + first * SLOT_W - 0.5 * mm - NAME_X - extra)
            c.setFillGray(0)
            c.setFont('DINC', size)
            c.drawString(x0 + NAME_X, basis(mid, size), s['kurz'])
            nx = x0 + NAME_X + pdfmetrics.stringWidth(s['kurz'], 'DINC', size) + 0.6 * mm
            for flag, ic in ((s['umweg_m'], 'umweg'), (s['schlaf'], 'schlaf')):
                if flag:
                    c.drawImage(str(ICON / f'{ic}.png'), nx, mid - 1.3 * mm, 2.6 * mm, 2.6 * mm, mask='auto')
                    nx += 3.0 * mm
            for i, ic in enumerate(s['slots']):
                if ic:
                    c.drawImage(str(ICON / f'{ic}.png'), x0 + SLOT_X + i * SLOT_W + (SLOT_W - ICO) / 2, mid - ICO / 2,
                                ICO, ICO, mask='auto')
    y -= FOOT
    if umwege:
        c.drawImage(str(ICON / 'umweg.png'), x0 + M + 0.6 * mm, y + 0.7 * mm, 2.2 * mm, 2.2 * mm, mask='auto')
        c.setFillGray(0.2)
        c.setFont('DINC', 6.4)
        c.drawString(x0 + M + 3.2 * mm, y + 1.15 * mm, f'UMWEG {umwege[0]} M' if len(umwege) == 1 else 'UMWEG')
    if any(s['haupt'] for s in stopps):
        c.setFillGray(0.3)
        c.setFont('DINC', 5.6)
        c.drawRightString(x0 + SW - M - 0.4 * mm, y + 1.15 * mm, 'GRAU = HAUPTSTOPP')


def schnittmarken(c, x0, y0, w, h, L=4 * mm, g=1.5 * mm):
    c.setStrokeGray(0)
    c.setLineWidth(0.25)
    for x, y, dx, dy in ((x0, y0, -1, -1), (x0 + w, y0, 1, -1), (x0, y0 + h, -1, 1), (x0 + w, y0 + h, 1, 1)):
        c.line(x + dx * g, y, x + dx * (g + L), y)
        c.line(x, y + dy * g, x, y + dy * (g + L))


pdf = OUT / f'{slug}-Sticker-{cfg["sticker_mm"][0]}x{cfg["sticker_mm"][1]}.pdf'
c = canvas.Canvas(str(pdf), pagesize=A4)
c.setTitle(f"{cfg['titel']} Vorbau-Sticker")
PW, PH = A4
c.setFont('ANC-Bold', 13)
c.drawString(20 * mm, PH - 20 * mm, f"{cfg['titel']}: Vorbau-Sticker {cfg['sticker_mm'][0]} x {cfg['sticker_mm'][1]} mm")
c.setFont('ANC-Demi', 9.5)
c.setFillGray(0.25)
c.drawString(20 * mm, PH - 26 * mm, 'Drucken mit 100 % (Tatsächliche Größe), nicht an die Seite anpassen. Die Kontrolllinie unten muss 50 mm messen.')
c.drawString(20 * mm, PH - 31 * mm, 'Zwei Exemplare: eins für den Vorbau, eins als Ersatz. Auf Etikettenpapier drucken oder mit Klebeband überkleben.')
gap = 25 * mm
x1 = (PW - 2 * SW - gap) / 2
ybot = PH - 42 * mm - SH
for xs in (x1, x1 + SW + gap):
    sticker(c, xs, ybot)
    schnittmarken(c, xs, ybot, SW, SH)
ly = ybot - 14 * mm
c.setStrokeGray(0)
c.setLineWidth(0.5)
c.line(x1, ly, x1 + 50 * mm, ly)
for xx in (x1, x1 + 50 * mm):
    c.line(xx, ly - 2 * mm, xx, ly + 2 * mm)
c.setFillGray(0)
c.setFont('ANC-Demi', 9)
c.drawString(x1 + 52 * mm, ly - 1.2 * mm, '50 mm')
ly -= 12 * mm
c.setFont('ANC-Bold', 10)
c.drawString(x1, ly, 'Symbole')
LABEL = {'laden': 'Supermarkt, Laden', 'automat': '24h-Automat', 'baecker': 'Bäcker', 'imbiss': 'Imbiss, Döner',
         'tanke': 'Tankstelle', 'rad': 'Radladen'}
items = [(k, v) for k, v in LABEL.items() if k in genutzt]
if umwege:
    items.append(('umweg', 'Umweg zum Laden'))
if any(s['schlaf'] for s in stopps):
    items.append(('schlaf', 'Abendessen und Schlafen'))
c.setFont('ANC-Demi', 9.5)
for k, (ic, label) in enumerate(items):
    xx, yy = x1 + (k % 2) * 55 * mm, ly - 7 * mm - (k // 2) * 6.5 * mm
    c.drawImage(str(ICON / f'{ic}.png'), xx, yy - 1 * mm, 4 * mm, 4 * mm, mask='auto')
    c.drawString(xx + 6 * mm, yy, label)
yy = ly - 12 * mm - ((len(items) + 1) // 2) * 6.5 * mm
c.setFont('ANC-Demi', 8.5)
c.setFillGray(0.35)
quelle = zeiten_quelle(stopps)  # "geprüft mit Google Maps" nur, wenn jede Option quelle google hat
for zeile in ('Spalten: Laden oder Automat | Bäcker oder Imbiss | Tankstelle | Radladen. KM = gefahrene km, REST = km bis zum Ziel.',
              'Grau hinterlegt: wichtige Stopps (vor einer Lücke, Essen und Schlafen, Frühstück, letzter Stopp).',
              f"Alle Symbole offen bei Planzeit mit {cfg['puffer_min']} Min. Puffer.", quelle):
    c.drawString(x1, yy, zeile)
    yy -= 5 * mm
c.showPage()
c.save()
print('PDF', pdf)
print('Sticker:', quelle)

# ---------------------------------------------------------------- Wallpaper (PNG)
k = W / 1206
P = lambda v: round(v * k)
F = lambda size: ImageFont.truetype(DIN, P(size))
A = lambda size, idx=2: ImageFont.truetype(ANC, P(size), index=idx)
EM = ImageFont.truetype(EMOJI_FONT, 160)
AMBER, WHITE, SOFT, GREY = (255, 179, 64), (255, 255, 255), (226, 229, 235), (140, 147, 160)
ORANGE, BAND_BG, BETT = (255, 159, 10), (33, 36, 45), (158, 197, 255)
cache = {}


def emoji(ch, size):
    if (ch, size) not in cache:
        tile = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((100, 100), ch, font=EM, embedded_color=True, anchor='mm')
        tile = tile.crop(tile.getbbox())
        f = size / max(tile.size)
        cache[(ch, size)] = tile.resize((max(1, round(tile.width * f)), max(1, round(tile.height * f))), Image.LANCZOS)
    return cache[(ch, size)]


def getoent(name, farbe, size):
    src = Image.open(ICON / f'{name}.png').convert('RGBA')
    bild = Image.new('RGBA', src.size, farbe + (255,))
    bild.putalpha(src.getchannel('A'))
    return bild.resize((size, size), Image.LANCZOS)


def cap(font):
    return -font.getbbox('H', anchor='ls')[1]


def wallpaper(seite, datei):
    img = Image.new('RGB', (W, H))
    px = img.load()
    for yy in range(H):
        t = yy / (H - 1)
        farbe = tuple(round(a + (b - a) * t) for a, b in zip((10, 11, 15), (24, 26, 33)))
        for xx in range(W):
            px[xx, yy] = farbe
    d = ImageDraw.Draw(img)
    paste = lambda im, x, y: img.paste(im, (round(x), round(y)), im)
    MX, GUT = P(44), P(34)
    spalten = len(seite)
    CW = (W - 2 * MX - GUT * (spalten - 1)) // spalten
    TOP, HEADH, BOTTOM = P(830), P(92), P(2250)
    nmax = max(len(rows) for _, rows in seite)
    ROWH = min(P(104), (BOTTOM - TOP - HEADH) // nmax)
    SLOT = P(54)
    fkm, frest, fhead = F(60), F(36), A(46, 0)
    for col, (tag, rows) in enumerate(seite):
        x0 = MX + col * (CW + GUT)
        hx = x0 + P(8)
        for ch in tag:
            d.text((hx, TOP + P(58)), ch, font=fhead, fill=AMBER, anchor='ls')
            hx += fhead.getlength(ch) + P(6)
        d.line((x0 + P(8), TOP + P(76), x0 + CW - P(8), TOP + P(76)), fill=(90, 72, 40), width=P(3))
        for i, s in enumerate(rows):
            y = TOP + HEADH + i * ROWH
            mid = y + ROWH / 2
            if s['haupt']:
                d.rounded_rectangle((x0, y + P(5), x0 + CW, y + ROWH - P(5)), radius=P(18), fill=BAND_BG)
                d.rounded_rectangle((x0, y + P(5), x0 + P(7), y + ROWH - P(5)), radius=P(3), fill=AMBER)
            kmx = x0 + P(96)
            d.text((kmx, mid + cap(fkm) / 2 - P(14)), str(round(s['km'])), font=fkm, fill=WHITE, anchor='rs')
            d.text((kmx, mid + cap(fkm) / 2 + P(26)), str(s['rest']), font=frest, fill=GREY, anchor='rs')
            first = next((j for j, v in enumerate(s['slots']) if v), 4)
            slotx = x0 + CW - 4 * SLOT - P(4)
            nx = x0 + P(114)
            maxw = slotx + first * SLOT - P(8) - nx - (P(56) if s['schlaf'] else 0)
            size = 48
            while size > 34 and F(size).getlength(s['kurz']) > maxw:
                size -= 1
            fn = F(size)
            farbe = ORANGE if s['umweg_m'] else (WHITE if s['haupt'] else SOFT)
            if s['umweg_m']:
                d.text((nx, mid + cap(fn) / 2 - P(14)), s['kurz'], font=fn, fill=farbe, anchor='ls')
                paste(getoent('umweg', ORANGE, P(30)), nx, mid + P(8))
                d.text((nx + P(36), mid + P(34)), f"{s['umweg_m']} m Umweg", font=A(30), fill=ORANGE, anchor='ls')
            else:
                d.text((nx, mid + cap(fn) / 2), s['kurz'], font=fn, fill=farbe, anchor='ls')
            if s['schlaf']:
                paste(getoent('schlaf', BETT, P(46)), nx + fn.getlength(s['kurz']) + P(14), mid - P(23))
            for j, ic in enumerate(s['slots']):
                if ic:
                    e = emoji(EMOJI[ic], P(45))
                    paste(e, slotx + j * SLOT + SLOT / 2 - e.width / 2, mid - e.height / 2)
    # Legende unter der kürzeren Spalte, sonst unter beiden
    kurz_col = min(range(spalten), key=lambda c_: len(seite[c_][1]))
    frei_ab = TOP + HEADH + len(seite[kurz_col][1]) * ROWH
    if BOTTOM - frei_ab >= P(250) and spalten > 1:
        lx0, ly = MX + kurz_col * (CW + GUT) + P(8), frei_ab + P(40)
    else:
        lx0, ly = MX + P(8), TOP + HEADH + nmax * ROWH + P(40)
    if ly + P(200) <= H - P(330):
        d.text((lx0, ly), 'SYMBOLE', font=A(30, 0), fill=GREY, anchor='ls')
        fl = A(32)
        eintraege = [(ic, lab) for ic, lab in (('laden', 'Laden'), ('baecker', 'Bäcker'), ('tanke', 'Tanke'),
                                               ('automat', 'Automat'), ('imbiss', 'Imbiss'), ('rad', 'Rad')) if ic in genutzt]
        for n, (ic, label) in enumerate(eintraege):
            cx, cy = lx0 + (n % 3) * P(172), ly + P(52) + (n // 3) * P(62)
            e = emoji(EMOJI[ic], P(40))
            paste(e, cx + P(20) - e.width / 2, cy - P(11) - e.height / 2)
            d.text((cx + P(48), cy), label, font=fl, fill=SOFT, anchor='ls')
        yb = ly + P(52) + ((len(eintraege) + 2) // 3) * P(62)
        x = lx0
        if umwege:
            paste(getoent('umweg', ORANGE, P(34)), x + P(3), yb - P(31))
            d.text((x + P(48), yb), 'Umweg', font=fl, fill=ORANGE, anchor='ls')
            x += P(172)
        if any(s['schlaf'] for _, rows in seite for s in rows):
            paste(getoent('schlaf', BETT, P(38)), x + P(2), yb - P(33))
            d.text((x + P(48), yb), 'Schlafen', font=fl, fill=SOFT, anchor='ls')
            x += P(172)
        if any(s['haupt'] for _, rows in seite for s in rows):
            d.rounded_rectangle((x + P(4), yb - P(26), x + P(12), yb + P(2)), radius=P(2), fill=AMBER)
            d.text((x + P(26), yb), 'Hauptstopp', font=fl, fill=SOFT, anchor='ls')
    img.save(datei, optimize=True)
    print('PNG', datei, img.size)


seiten = [tage[i:i + 2] for i in range(0, len(tage), 2)]
for n, seite in enumerate(seiten, 1):
    zusatz = f'-{n}' if len(seiten) > 1 else ''
    wallpaper(seite, OUT / f"{slug}-Wallpaper-{cfg['iphone'].replace(' ', '')}{zusatz}.png")
