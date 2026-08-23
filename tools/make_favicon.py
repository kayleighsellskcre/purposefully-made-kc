"""Regenerate static/favicon.ico and the PNG touch icons from the brand monogram.

Run from the project root after the logo changes:
    py -3.12 tools/make_favicon.py

The monogram is not square, so it is centred on a transparent square canvas
first — squashing it to fit would distort the mark.
"""
import os

from PIL import Image

SOURCE = os.path.join('static', 'img', 'logo-monogram.png')
ICO_PATH = os.path.join('static', 'favicon.ico')
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
PNG_ICONS = {
    os.path.join('static', 'img', 'favicon-32.png'): 32,
    os.path.join('static', 'img', 'favicon-192.png'): 192,
    os.path.join('static', 'img', 'apple-touch-icon.png'): 180,
}
# Apple ignores transparency and composites on black, so give iOS a real
# background drawn from the brand cream.
APPLE_BACKGROUND = (245, 240, 232, 255)


def squared(image, padding_ratio=0.06):
    """Centre the mark on a transparent square canvas with a little breathing room."""
    width, height = image.size
    side = int(max(width, height) * (1 + padding_ratio * 2))
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - width) // 2, (side - height) // 2), image)
    return canvas


def main():
    source = Image.open(SOURCE).convert('RGBA')
    base = squared(source)

    base.save(ICO_PATH, format='ICO', sizes=ICO_SIZES)
    print(f'wrote {ICO_PATH} with sizes {ICO_SIZES}')

    for path, size in PNG_ICONS.items():
        icon = base.resize((size, size), Image.LANCZOS)
        if 'apple-touch-icon' in path:
            flat = Image.new('RGBA', icon.size, APPLE_BACKGROUND)
            flat.paste(icon, (0, 0), icon)
            icon = flat
        icon.save(path, format='PNG', optimize=True)
        print(f'wrote {path} ({size}x{size})')


if __name__ == '__main__':
    main()
