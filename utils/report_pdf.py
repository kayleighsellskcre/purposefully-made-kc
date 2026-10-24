"""Profit and loss as a PDF: one page for a period, and a monthly table for a year."""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.ledger import dollars

INK = colors.HexColor('#3A3D48')
MUTED = colors.HexColor('#7A7C86')
ROSE = colors.HexColor('#B87C6F')
SAND = colors.HexColor('#E8D0B1')
CREAM = colors.HexColor('#FBF6EE')


def _st(name, **kw):
    kw.setdefault('textColor', INK)
    kw.setdefault('fontName', 'Helvetica')
    kw.setdefault('fontSize', 10)
    kw.setdefault('leading', kw['fontSize'] * 1.3)
    return ParagraphStyle(name, **kw)


S = {
    'brand': _st('brand', fontSize=8.5, fontName='Helvetica-Bold', textColor=ROSE, alignment=TA_CENTER),
    'title': _st('title', fontSize=26, fontName='Times-Roman', alignment=TA_CENTER, leading=30),
    'sub': _st('sub', fontSize=9.5, textColor=MUTED, alignment=TA_CENTER),
    'row': _st('row'), 'rowr': _st('rowr', alignment=TA_RIGHT),
    'sec': _st('sec', fontName='Helvetica-Bold', fontSize=8.5, textColor=ROSE),
    'bold': _st('bold', fontName='Helvetica-Bold'), 'boldr': _st('boldr', fontName='Helvetica-Bold', alignment=TA_RIGHT),
    'note': _st('note', fontSize=8.5, textColor=MUTED),
    'cell': _st('cell', fontSize=7.4, leading=9), 'cellr': _st('cellr', fontSize=7.4, leading=9, alignment=TA_RIGHT),
    'cellb': _st('cellb', fontSize=7.4, leading=9, fontName='Helvetica-Bold'),
    'cellbr': _st('cellbr', fontSize=7.4, leading=9, fontName='Helvetica-Bold', alignment=TA_RIGHT),
}


def _header(title, label, business):
    return [Paragraph(business.get('name', 'Purposefully Made KC').upper(), S['brand']), Spacer(1, 3),
            Paragraph(title, S['title']), Spacer(1, 2),
            Paragraph(f'{label} &nbsp;&middot;&nbsp; Cash basis &nbsp;&middot;&nbsp; Kansas City time', S['sub']),
            Spacer(1, 8), HRFlowable(width='100%', thickness=0.6, color=SAND, spaceAfter=8)]


def build_pnl_pdf(p, label, business, *, channels=(), estimates=None):
    """p is utils.ledger.pnl(). Returns PDF bytes."""
    rows, styles = [], []

    def line(text, cents=None, *, bold=False, indent=0, rule=False, section=False, tint=False):
        left = Paragraph(('&nbsp;' * indent) + text, S['sec'] if section else S['bold' if bold else 'row'])
        right = Paragraph('' if cents is None else dollars(cents), S['boldr' if bold else 'rowr'])
        rows.append([left, right])
        i = len(rows) - 1
        styles.append(('LINEBELOW', (0, i), (-1, i), 0.25, SAND))
        if rule:
            styles.append(('LINEABOVE', (0, i), (-1, i), 0.8, INK))
        if tint:
            styles.append(('BACKGROUND', (0, i), (-1, i), CREAM))

    line('INCOME', section=True, tint=True)
    line('Gross sales (merchandise and shipping charged)', p['gross_sales'], indent=2)
    line('Discounts', p['discounts'], indent=2)
    line('Refunds', p['refunds'], indent=2)
    line('Net sales', p['net_sales'], bold=True, rule=True)
    line('Cost of goods', -p['cogs'], indent=2)
    line('Gross profit', p['gross_profit'], bold=True, rule=True)
    if p['other_income']:
        line('Other income', p['other_income'], indent=2)
    line('EXPENSES', section=True, tint=True)
    for name, cents in p['expenses']:
        line(name, -cents, indent=2)
    if not p['expenses']:
        line('No expenses in this period', indent=2)
    line('Total expenses', -p['total_expenses'], bold=True, rule=True)
    line('Net profit', p['net_profit'], bold=True, rule=True, tint=True)

    table = Table(rows, colWidths=[5.2 * inch, 2.1 * inch])
    table.setStyle(TableStyle(styles + [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 4),
                                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))

    below = Table([
        [Paragraph('Sales tax collected (owed to the state, not income)', S['row']), Paragraph(dollars(p['tax_collected']), S['rowr'])],
        [Paragraph('Owner contributions (money you put in)', S['row']), Paragraph(dollars(p['contributions']), S['rowr'])],
        [Paragraph('Owner draws (money you took out)', S['row']), Paragraph(dollars(p['draws']), S['rowr'])],
    ], colWidths=[5.2 * inch, 2.1 * inch])
    below.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.25, SAND), ('TOPPADDING', (0, 0), (-1, -1), 3),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))

    story = _header('Profit and Loss', label, business) + [table, Spacer(1, 14),
                                                           Paragraph('BELOW THE LINE', S['sec']), Spacer(1, 3), below]
    if channels:
        chan = Table([[Paragraph(n, S['row']), Paragraph(dollars(c), S['rowr'])] for n, c in channels],
                     colWidths=[5.2 * inch, 2.1 * inch])
        chan.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.25, SAND), ('TOPPADDING', (0, 0), (-1, -1), 3),
                                  ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
        story += [Spacer(1, 12), Paragraph('NET SALES BY CHANNEL', S['sec']), Spacer(1, 3), chan]
    if estimates and (estimates.get('fees') or estimates.get('cogs')):
        story += [Spacer(1, 10), Paragraph(
            f"Heads up: {estimates.get('fees', 0)} paid order(s) still use an estimated processing fee and "
            f"{estimates.get('cogs', 0)} an estimated cost of goods. Those figures change when the real amounts arrive.",
            S['note'])]
    story += [Spacer(1, 10), Paragraph('This report is not tax advice. Confirm categories and methods with your CPA.', S['note'])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch, topMargin=0.55 * inch,
                      bottomMargin=0.5 * inch, title=f'Profit and Loss {label}',
                      author=business.get('name') or 'Purposefully Made KC').build(story)
    return buf.getvalue()


def build_monthly_pdf(year, months, business):
    """months: [(label, pnl)] for twelve months. Whole dollars keep twelve columns readable."""
    def whole(cents):
        cents = int(cents)
        return ('-' if cents < 0 else '') + f'${abs(cents) / 100:,.0f}'

    heads = [''] + [m for m, _p in months] + ['Year']
    lines = [
        ('Net sales', lambda x: x['net_sales'], False), ('Cost of goods', lambda x: -x['cogs'], False),
        ('Gross profit', lambda x: x['gross_profit'], True), ('Expenses', lambda x: -x['total_expenses'], False),
        ('Net profit', lambda x: x['net_profit'], True), ('Sales tax collected', lambda x: x['tax_collected'], False),
    ]
    data = [[Paragraph(h, S['cellbr' if h else 'cellb']) for h in heads]]
    styles = [('LINEBELOW', (0, 0), (-1, 0), 0.8, INK), ('BACKGROUND', (0, 0), (-1, 0), CREAM)]
    for name, fn, bold in lines:
        vals = [fn(p) for _m, p in months]
        cells = [Paragraph(name, S['cellb' if bold else 'cell'])] + [Paragraph(whole(v), S['cellbr' if bold else 'cellr']) for v in vals]
        cells.append(Paragraph(whole(sum(vals)), S['cellbr']))
        data.append(cells)
        styles.append(('LINEBELOW', (0, len(data) - 1), (-1, len(data) - 1), 0.25, SAND))
    width = 10.0 * inch
    table = Table(data, colWidths=[1.25 * inch] + [0.6 * inch] * 12 + [0.75 * inch])
    table.setStyle(TableStyle(styles + [('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    story = _header('Monthly Profit and Loss', str(year), business) + [table, Spacer(1, 10),
            Paragraph('Whole dollars. Months are Kansas City months. Not tax advice; confirm with your CPA.', S['note'])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                      topMargin=0.55 * inch, bottomMargin=0.5 * inch, title=f'Monthly Profit and Loss {year}',
                      author=business.get('name') or 'Purposefully Made KC').build(story)
    return buf.getvalue()


def build_sales_tax_pdf(report, label, business, rate_percent):
    """Sales tax by where each sale was taxed. report is utils.ledger.sales_tax_report()."""
    head = ['Where taxed', 'Orders', 'Taxable sales', 'Not taxed', 'Shipping', 'Tax collected']
    data = [[Paragraph(h, S['cellb' if i == 0 else 'cellbr']) for i, h in enumerate(head)]]
    styles = [('LINEBELOW', (0, 0), (-1, 0), 0.8, INK), ('BACKGROUND', (0, 0), (-1, 0), CREAM)]
    for r in report['rows']:
        data.append([Paragraph(r['label'], S['cell']), Paragraph(str(r['orders']), S['cellr']),
                     Paragraph(dollars(r['taxable']), S['cellr']), Paragraph(dollars(r['not_taxed']), S['cellr']),
                     Paragraph(dollars(r['shipping']), S['cellr']), Paragraph(dollars(r['tax']), S['cellr'])])
        styles.append(('LINEBELOW', (0, len(data) - 1), (-1, len(data) - 1), 0.25, SAND))
    t = report['totals']
    data.append([Paragraph('Total', S['cellb']), Paragraph(str(t['orders']), S['cellbr']), Paragraph(dollars(t['taxable']), S['cellbr']),
                 Paragraph(dollars(t['not_taxed']), S['cellbr']), Paragraph(dollars(t['shipping']), S['cellbr']),
                 Paragraph(dollars(t['tax']), S['cellbr'])])
    styles.append(('LINEABOVE', (0, len(data) - 1), (-1, len(data) - 1), 0.8, INK))
    table = Table(data, colWidths=[2.5 * inch, 0.6 * inch, 1.1 * inch, 1.0 * inch, 0.9 * inch, 1.2 * inch])
    table.setStyle(TableStyle(styles + [('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    story = _header('Sales Tax Report', label, business) + [table, Spacer(1, 10)]
    story.append(Paragraph(f'Rate in use today: {rate_percent:g}%. Shipping is not taxed. Refunds are subtracted on the day they went out.', S['note']))
    if report['out_of_state_tax']:
        story += [Spacer(1, 6), Paragraph(
            f"Heads up: {dollars(report['out_of_state_tax'])} of Kansas tax was collected on orders shipped out of state "
            'before that stopped. Ask your CPA how to handle it.', S['note'])]
    story += [Spacer(1, 8), Paragraph('This report is not tax advice. Confirm the rate and the filing with your CPA.', S['note'])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch, topMargin=0.55 * inch,
                      bottomMargin=0.5 * inch, title=f'Sales Tax {label}',
                      author=business.get('name') or 'Purposefully Made KC').build(story)
    return buf.getvalue()
