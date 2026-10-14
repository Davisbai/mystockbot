"""Conservative daily-bar completion checks for displayed entry signals."""
import datetime
import pytz


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
