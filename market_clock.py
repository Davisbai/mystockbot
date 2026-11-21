"""Conservative daily-bar completion checks for displayed entry signals."""
import datetime
import pytz
from app_support import source_digest
RUNTIME_SOURCE_SHA256 = source_digest(__file__)


def daily_bar_closed(ticker, bar_date, now=None):
    zone = pytz.timezone('Asia/Taipei' if ticker.endswith(('.TW', '.TWO')) else 'America/New_York')
    local_now = datetime.datetime.now(zone) if now is None else now.astimezone(zone)
    date = datetime.date.fromisoformat(bar_date)
    if date < local_now.date():
        return True
    if date > local_now.date():
        return False
    # Include a publication buffer; this is a bar check, not a market calendar.
    cutoff = datetime.time(13, 40) if ticker.endswith(('.TW', '.TWO')) else datetime.time(16, 15)
    return local_now.time().replace(tzinfo=None) >= cutoff


def expected_tw_market_date(now=None):
    """Latest weekday whose TW daily bar should be complete (ignores holidays)."""
    zone = pytz.timezone('Asia/Taipei')
    local_now = datetime.datetime.now(zone) if now is None else now.astimezone(zone)
    day = local_now.date()
    if local_now.time().replace(tzinfo=None) < datetime.time(13, 40):
        day -= datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def report_already_sent(directory='daily_reports', now=None):
    """True when the expected market date's report was already delivered."""
    import json, pathlib
    file = pathlib.Path(directory) / f'{expected_tw_market_date(now)}.json'
    try:
        report = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return (report.get('delivery') or {}).get('status') == 'sent'


if __name__ == '__main__':
    import sys
    # Exit 0 = need to scan; exit 10 = already delivered, skip.
    sys.exit(10 if report_already_sent() else 0)
