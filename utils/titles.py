"""Title-casing that knows small words and acronyms: "Kc Heart Of The Midwest" becomes "KC Heart of the Midwest"."""
import re

SMALL_WORDS = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to', 'vs', 'with'}
ACRONYMS = {'kc', 'usa', 'us', 'dj', 'mvp', 'pto', 'pta', 'stem', 'nfl', 'nba', 'mlb', 'nhl', 'uk', 'tv', 'diy',
            'ok', 'ai', 'pe', 'bff', 'vip', 'lol', 'omg', 'ymca', 'hs', 'jv', 'ap'}


def smart_title(text):
    words = re.sub(r'\s+', ' ', (text or '').strip()).split(' ')
    out = []
    for i, word in enumerate(words):
        core = re.sub(r'[^A-Za-z]', '', word)
        low = core.lower()
        if not core:
            out.append(word)
        elif low in ACRONYMS:
            out.append(re.sub(r'[A-Za-z]+', core.upper(), word, count=1))
        elif low in SMALL_WORDS and 0 < i < len(words) - 1 and not words[i - 1].endswith((':', '-')):
            out.append(word.lower())
        else:
            out.append(word[:1].upper() + word[1:].lower() if word.isupper() or word.islower() or word.istitle() else word)
    return ' '.join(out)
