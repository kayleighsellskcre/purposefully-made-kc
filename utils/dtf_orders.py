"""Weekly DTF shopping list from open production orders.

Nothing is purchased here. This is the list Kayleigh takes to her DTF site:
upload the PNG, type the size, set the quantity.
"""
from utils.order_artwork import front_print_url
from utils.print_sizes import inches, production_from_order_item


def _label(value):
    return (value or '').replace('_', ' ').strip() or '—'


def _copy_logo(name, placement, width, qty):
    return f'{name} · {placement} · {width:.2f}" wide × {qty}'


def _copy_personal(name, number, name_h, number_h, qty):
    who = ' '.join(part for part in (name, f'#{number}' if number else '') if part).strip() or 'Back'
    lines = [who]
    if name:
        lines.append(f'  Name {name_h:.2f}" high × {qty}')
    if number:
        lines.append(f'  Number {number_h:.2f}" high × {qty}')
    return '\n'.join(lines)


def build_dtf_shopping_list(orders):
    """Group identical logos; keep each name/number as its own upload."""
    logos = {}
    personal = []
    order_ids = set()

    for order in orders:
        for item in order.items:
            prod = production_from_order_item(item, customer_name=order.full_name) or {}
            qty = int(item.quantity or 1)
            if qty < 1:
                continue
            order_ids.add(order.id)

            front = prod.get('front')
            if front:
                width = inches(front.get('width'))
                height = inches(front.get('height'))
                name = (front.get('design_name') or item.design_file_name or 'Logo').strip() or 'Logo'
                placement = front.get('placement_label') or _label(item.placement)
                preview = front_print_url(item)
                key = (
                    item.design_id or preview or name.lower(),
                    (item.placement or '').lower(),
                    width,
                    height,
                )
                row = logos.get(key)
                if not row:
                    row = {
                        'design_name': name,
                        'placement': placement,
                        'width': width,
                        'height': height,
                        'width_display': f'{width:.2f}' if width is not None else 'N/A',
                        'height_display': f'{height:.2f}' if height is not None else 'N/A',
                        'quantity': 0,
                        'preview_url': preview,
                        'order_id': order.id,
                        'item_id': item.id,
                    }
                    logos[key] = row
                row['quantity'] += qty

            back = prod.get('back')
            if back and (back.get('name') or back.get('number')):
                name_h = inches(back.get('name_height')) or 0
                number_h = inches(back.get('number_height')) or 0
                personal.append({
                    'name': (back.get('name') or '').strip(),
                    'number': str(back.get('number') or '').strip(),
                    'name_width_display': back.get('name_width_display'),
                    'name_height_display': back.get('name_height_display'),
                    'number_width_display': back.get('number_width_display'),
                    'number_height_display': back.get('number_height_display'),
                    'combined_width_display': back.get('combined_width_display'),
                    'combined_height_display': back.get('combined_height_display'),
                    'quantity': qty,
                    'order_id': order.id,
                    'item_id': item.id,
                    'order_number': order.order_number,
                    'copy_text': _copy_personal(
                        back.get('name'),
                        back.get('number'),
                        name_h,
                        number_h,
                        qty,
                    ),
                })

    logo_list = []
    for row in sorted(
        logos.values(),
        key=lambda r: (r['design_name'].lower(), r['placement'], r['width'] or 0),
    ):
        row['copy_text'] = _copy_logo(
            row['design_name'],
            row['placement'],
            row['width'] or 0,
            row['quantity'],
        )
        logo_list.append(row)

    personal.sort(key=lambda r: ((r['name'] or '').lower(), r['number'] or ''))

    copy_parts = []
    logo_copy = '\n'.join(row['copy_text'] for row in logo_list)
    personal_copy = '\n\n'.join(row['copy_text'] for row in personal)
    if logo_list:
        copy_parts.append('LOGOS — on the DTF site, set WIDTH, then quantity')
        copy_parts.append(logo_copy)
    if personal:
        if copy_parts:
            copy_parts.append('')
        copy_parts.append('NAMES & NUMBERS — on the DTF site, set HEIGHT, then quantity')
        copy_parts.append(personal_copy)

    csv_rows = []
    for row in logo_list:
        csv_rows.append({
            'kind': 'logo',
            'design_or_name': row['design_name'],
            'placement': row['placement'],
            'order_by': 'WIDTH',
            'size_in': row['width_display'],
            'height_in': row['height_display'],
            'quantity': row['quantity'],
            'order_number': '',
        })
    for row in personal:
        who = ' '.join(part for part in (row['name'], f"#{row['number']}" if row['number'] else '') if part)
        csv_rows.append({
            'kind': 'name_number',
            'design_or_name': who,
            'placement': 'Center back',
            'order_by': 'HEIGHT',
            'size_in': row['name_height_display'] or row['number_height_display'] or '',
            'height_in': row['combined_height_display'] or '',
            'quantity': row['quantity'],
            'order_number': row['order_number'] or '',
        })

    return {
        'logos': logo_list,
        'personal': personal,
        'all_copy': '\n'.join(copy_parts),
        'logo_copy': logo_copy,
        'personal_copy': personal_copy,
        'logo_count': len(logo_list),
        'personal_count': len(personal),
        'logo_qty': sum(r['quantity'] for r in logo_list),
        'personal_qty': sum(r['quantity'] for r in personal),
        'order_count': len(order_ids),
        'csv_rows': csv_rows,
        'has_items': bool(logo_list or personal),
    }
