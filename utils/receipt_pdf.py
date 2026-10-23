"""A one-page PDF receipt for a hand-made invoice.

The page is built, and if the invoice is long it is built again a little smaller, until everything fits on one
US Letter sheet. The same file is attached to the "payment received" email and offered as a download, so what a
customer prints is always one page.
"""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor('#3A3D48')
MUTED = colors.HexColor('#7A7C86')
ROSE = colors.HexColor('#B87C6F')
SAND = colors.HexColor('#E8D0B1')
SCALES = (1.0, 0.92, 0.85, 0.78, 0.7, 0.62, 0.55, 0.5)


def _esc(text):
    return (str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _money(value):
    return f'${float(value or 0):,.2f}'


def _styles(k):
    def style(name, **kw):
        kw.setdefault('textColor', INK)
        kw.setdefault('fontName', 'Helvetica')
        kw['fontSize'] = kw.get('fontSize', 10) * k
        kw['leading'] = kw['fontSize'] * 1.35
        return ParagraphStyle(name, **kw)
    return {
        'brand': style('brand', fontSize=9, fontName='Helvetica-Bold', textColor=ROSE, alignment=TA_CENTER, spaceAfter=4 * k),
        'title': style('title', fontSize=30, fontName='Times-Roman', alignment=TA_CENTER),
        'stamp': style('stamp', fontSize=11, fontName='Helvetica-Bold', textColor=ROSE, alignment=TA_CENTER),
        'meta': style('meta', fontSize=9.5, textColor=MUTED, alignment=TA_CENTER),
        'label': style('label', fontSize=8, fontName='Helvetica-Bold', textColor=MUTED),
        'body': style('body', fontSize=10),
        'cell': style('cell', fontSize=10),
        'cellr': style('cellr', fontSize=10, alignment=TA_RIGHT),
        'head': style('head', fontSize=8, fontName='Helvetica-Bold', textColor=MUTED),
        'headr': style('headr', fontSize=8, fontName='Helvetica-Bold', textColor=MUTED, alignment=TA_RIGHT),
        'tot': style('tot', fontSize=10, alignment=TA_RIGHT),
        'grand': style('grand', fontSize=14, fontName='Times-Bold', alignment=TA_RIGHT),
        'thanks': style('thanks', fontSize=12, fontName='Times-Italic', alignment=TA_CENTER, textColor=INK),
        'foot': style('foot', fontSize=8.5, textColor=MUTED, alignment=TA_CENTER),
    }


def _story(doc_data, business, paid_on, k):
    s = _styles(k)
    d = doc_data
    paid_full = d['balance'] <= 0
    unpaid = (d.get('paid') or 0) <= 0
    title = 'Invoice' if unpaid else ('Receipt' if paid_full else 'Payment Receipt')
    out = [
        Paragraph('PURPOSEFULLY MADE KC', s['brand']),
        Paragraph(title, s['title']),
        Spacer(1, 4 * k),
        Paragraph(f"BALANCE DUE {_money(d['balance'])}" if unpaid else
                  ('PAID IN FULL' if paid_full else f"PAYMENT RECEIVED, BALANCE {_money(d['balance'])}"), s['stamp']),
        Spacer(1, 4 * k),
        Paragraph(f"{_esc(d['number'])} &nbsp;&middot;&nbsp; {_esc(paid_on or d['date'])}", s['meta']),
        Spacer(1, 10 * k),
        HRFlowable(width='100%', thickness=0.6, color=SAND, spaceAfter=10 * k),
    ]

    who = [Paragraph('BILLED TO', s['label'])]
    for part in (d.get('company'), d.get('attn') or d.get('name'), d.get('email'), d.get('phone')):
        if part:
            who.append(Paragraph(_esc(part), s['body']))
    for line in str(d.get('address') or '').splitlines():
        if line.strip():
            who.append(Paragraph(_esc(line), s['body']))
    from_ = [Paragraph('FROM', s['label']), Paragraph(_esc(business.get('name')), s['body']),
             Paragraph(_esc(business.get('email')), s['body']), Paragraph(_esc(business.get('phone')), s['body'])]
    pay = []
    if d.get('method') and not unpaid:
        pay = [Paragraph('PAID BY', s['label']), Paragraph(_esc(d['method']), s['body'])]
    if d.get('po'):
        pay += [Spacer(1, 6), Paragraph('PO', s['label']), Paragraph(_esc(d['po']), s['body'])]
    cols = [who, from_] + ([pay] if pay else [])
    party = Table([cols], colWidths=[(7.3 * inch) / len(cols)] * len(cols))
    party.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    out += [party, Spacer(1, 12 * k)]

    rows = [[Paragraph('DESCRIPTION', s['head']), Paragraph('QTY', s['headr']),
             Paragraph('PRICE', s['headr']), Paragraph('AMOUNT', s['headr'])]]
    for line in d['lines']:
        qty = f"{line['qty']:g}"
        rows.append([Paragraph(_esc(line['name']), s['cell']), Paragraph(qty, s['cellr']),
                     Paragraph(_money(line.get('unit', 0)), s['cellr']), Paragraph(_money(line['total']), s['cellr'])])
    table = Table(rows, colWidths=[3.9 * inch, 0.7 * inch, 1.2 * inch, 1.5 * inch], repeatRows=0)
    table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, SAND), ('LINEBELOW', (0, 1), (-1, -1), 0.25, SAND),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5 * k), ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5 * k),
    ]))
    out += [table, Spacer(1, 8 * k)]

    tot = []
    tot.append(['Subtotal', _money(d['subtotal'])])
    if d.get('discount'):
        tot.append(['Discount', '-' + _money(d['discount'])])
    if d.get('shipping'):
        tot.append(['Shipping', _money(d['shipping'])])
    tot.append([d.get('tax_label') or 'Tax', _money(d['tax'])])
    tot.append(['Total', _money(d['total'])])
    if not unpaid:
        tot.append(['Paid', _money(d['paid'])])
    cells = [[Paragraph(a, s['tot']), Paragraph(b, s['tot'])] for a, b in tot]
    cells.append([Paragraph('Balance due' if not paid_full else 'Balance', s['grand']),
                  Paragraph(_money(d['balance']), s['grand'])])
    totals = Table(cells, colWidths=[1.6 * inch, 1.3 * inch], hAlign='RIGHT')
    totals.setStyle(TableStyle([('TOPPADDING', (0, 0), (-1, -1), 1.5 * k), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5 * k),
                                ('LINEABOVE', (0, -1), (-1, -1), 0.6, SAND), ('TOPPADDING', (0, -1), (-1, -1), 6 * k)]))
    out += [totals, Spacer(1, 16 * k)]

    if d.get('note'):
        out += [Paragraph('NOTE', s['label']), Paragraph(_esc(d['note']).replace('\n', '<br/>'), s['body']), Spacer(1, 12 * k)]
    out += [HRFlowable(width='100%', thickness=0.6, color=SAND, spaceBefore=4 * k, spaceAfter=10 * k),
            Paragraph('Thank you for supporting a small local business.', s['thanks']), Spacer(1, 4 * k),
            Paragraph(f"Questions? Reply to your email or reach us at {_esc(business.get('email'))} "
                      f"or {_esc(business.get('phone'))}.", s['foot'])]
    return out


def build_receipt_pdf(doc_data, business, paid_on=None):
    """Return the PDF bytes. The sheet is shrunk step by step until it is a single page."""
    data = None
    for k in SCALES:
        buf = io.BytesIO()
        pdf = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                                topMargin=0.55 * inch, bottomMargin=0.5 * inch,
                                title=f"{doc_data['number']}", author=business.get('name') or 'Purposefully Made KC')
        pdf.build(_story(doc_data, business, paid_on, k))
        data = buf.getvalue()
        if pdf.page == 1:
            return data
    return data
