"""Votes: someone uploads their own pictures, shares one link, and sees who picked what.

Everything hangs off the poll, so one person's vote can never touch another's: options and answers belong to a
single poll, and a submitted pick is only accepted if the option belongs to the poll being voted in.
"""
import secrets

from models import VoteChoice, VoteOption, VotePoll, VoteResponse, db

MAX_PICTURES = 12
MIN_PICTURES = 2
IMAGE_TYPES = ('png', 'jpg', 'jpeg', 'webp', 'gif')


def new_token():
    return secrets.token_urlsafe(16).replace('-', 'a').replace('_', 'b')[:22]


def get_poll(token):
    return VotePoll.query.filter_by(token=str(token or '')).first()


def is_picture(file_storage):
    name = (getattr(file_storage, 'filename', '') or '').lower()
    return '.' in name and name.rsplit('.', 1)[-1] in IMAGE_TYPES


def create_poll(user, title, note, urls):
    poll = VotePoll(token=new_token(), user_id=user.id, title=title.strip()[:200], note=(note or '').strip()[:500] or None)
    for i, url in enumerate(urls):
        poll.options.append(VoteOption(image_url=url, position=i + 1))
    db.session.add(poll)
    db.session.commit()
    return poll


def submit(poll, name, option_ids):
    """Record a vote. Returns (response, error). The same name voting again in this poll replaces their earlier vote."""
    name = ' '.join(str(name or '').split())[:120]
    if not poll.is_open:
        return None, 'This vote is closed.'
    if not name:
        return None, 'Please enter your name before you submit.'
    valid = {o.id for o in poll.options}
    picks = []
    for raw in option_ids:
        try:
            oid = int(raw)
        except (TypeError, ValueError):
            continue
        if oid in valid and oid not in picks:
            picks.append(oid)
    if not picks:
        return None, 'Please pick at least one design, then press Submit.'
    for old in [r for r in poll.responses if r.voter_name.lower() == name.lower()]:
        db.session.delete(old)
    response = VoteResponse(poll_id=poll.id, voter_name=name)
    for oid in picks:
        response.picks.append(VoteChoice(option_id=oid))
    db.session.add(response)
    db.session.commit()
    return response, None


def tally(poll):
    """Each option with its number, vote count and the names who picked it, most votes first."""
    names = {o.id: [] for o in poll.options}
    for r in poll.responses:
        for c in r.picks:
            if c.option_id in names:
                names[c.option_id].append(r.voter_name)
    rows = [{'option': o, 'number': o.position, 'count': len(names[o.id]), 'names': names[o.id]} for o in poll.options]
    return sorted(rows, key=lambda r: (-r['count'], r['number']))


def csv_text(poll):
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Name', 'Picked designs', 'Submitted'])
    for r in poll.responses:
        nums = sorted(next((o.position for o in poll.options if o.id == c.option_id), 0) for c in r.picks)
        w.writerow([r.voter_name, ', '.join(str(n) for n in nums), r.created_at.strftime('%Y-%m-%d %H:%M')])
    w.writerow([])
    w.writerow(['Design', 'Votes'])
    for row in tally(poll):
        w.writerow([row['number'], row['count']])
    return out.getvalue()
