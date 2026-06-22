"""Lidl (Ireland) receipt text parser.

Lifted verbatim from the original PyQt5 desktop app so that parsing behaviour
is identical across desktop and Android. Pure standard library, no UI deps.
"""
import re
from datetime import datetime

PRICE_LINE = re.compile(r'^(?P<name>.+?)\s{2,}(?P<price>\d+\.\d{2})\s+(?P<vat>[A-F])\s*$')
PRICE_LINE_LOOSE = re.compile(r'^(?P<name>.+?)\s+(?P<price>\d+\.\d{2})\s+(?P<vat>[A-F])\s*$')
QTY_LINE = re.compile(r'^\s*(?P<qty>\d+)\s*[xX]\s*(?P<unit>\d+\.\d{2})\s*$')
DISCOUNT = re.compile(r'-(?P<amt>\d+\.\d{2})\s*$')
TRN = re.compile(r'TRN-ID:\s*(\S+)')
DATE = re.compile(r'Date:\s*(\d{2}/\d{2}/\d{2})')
TOTAL = re.compile(r'^TOTAL\s+(\d+\.\d{2})\s*$')
STORE = re.compile(r'^([A-Za-z].+?)\s+-\s+IE\w+')
SKIP_NAME = re.compile(r'deposit', re.IGNORECASE)


def _is_noise(line):
    s = line.strip()
    if not s:
        return True
    if set(s) <= set('-= '):
        return True
    if s in ('EUR', 'Copy', 'More to Value.'):
        return True
    return False


def parse_receipt(text):
    """Parse raw receipt text into {store, date, trn_id, total, items[]}."""
    lines = text.splitlines()
    store = trn_id = rdate = total = None

    for ln in lines:
        if store is None:
            m = STORE.search(ln)
            if m:
                store = m.group(1).strip()
        m = TRN.search(ln)
        if m:
            trn_id = m.group(1).strip()
        m = DATE.search(ln)
        if m:
            try:
                rdate = datetime.strptime(m.group(1), '%d/%m/%y').date().isoformat()
            except ValueError:
                pass

    items = []
    current = None
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        m = TOTAL.match(stripped)
        if m:
            total = float(m.group(1))
            break
        if _is_noise(line):
            continue

        mq = QTY_LINE.match(stripped)
        if mq and current is not None:
            current['qty'] = int(mq.group('qty'))
            continue

        md = DISCOUNT.search(stripped)
        if md and current is not None:
            current['discount'] -= float(md.group('amt'))
            continue

        mp = PRICE_LINE.match(stripped) or PRICE_LINE_LOOSE.match(stripped)
        if mp:
            name = mp.group('name').strip()
            current = {
                'name': name,
                'gross': float(mp.group('price')),
                'vat': mp.group('vat'),
                'qty': 1,
                'discount': 0.0,
                'deposit': bool(SKIP_NAME.search(name)),
            }
            items.append(current)

    products = []
    for it in items:
        if it['deposit']:
            continue
        net = round(it['gross'] + it['discount'], 2)
        qty = it['qty'] or 1
        products.append({
            'name': it['name'],
            'qty': qty,
            'unit_price': round(net / qty, 2) if qty else net,
            'line_total': net,
            'vat': it['vat'],
        })

    return {'store': store, 'date': rdate, 'trn_id': trn_id,
            'total': total, 'items': products}
