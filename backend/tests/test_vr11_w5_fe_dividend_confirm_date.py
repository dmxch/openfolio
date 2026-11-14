"""R-importtx-1: Vertrag hinter dem Datumsvorschlag im Dialog «Dividende erfassen».

Der Dialog schlägt das kleinere von Ex-Date plus 14 Tage und heute (Ortszeit)
vor. Das trägt nur, solange ``ConfirmDividendRequest.date`` heute annimmt, auch
wenn die Ortszeit dem UTC-Datum einen Tag voraus ist, und ein Datum weiter in
der Zukunft ablehnt.
"""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from api.dividends import ConfirmDividendRequest
from api.validation import BOOKING_DATE_ERROR
from dateutils import utcnow


def _request(day):
    return ConfirmDividendRequest(date=day, total_chf=19.5)


@pytest.mark.parametrize("offset_days", [-1, 0, 1])
def test_confirm_accepts_today_in_any_timezone(offset_days):
    """Heute Ortszeit ist UTC-heute, einen Tag davor oder einen Tag danach."""
    day = utcnow().date() + timedelta(days=offset_days)

    assert _request(day).date == day


@pytest.mark.parametrize("ex_date_days_ago", [0, 1, 3, 12])
def test_confirm_rejects_ex_date_plus_14_while_in_future(ex_date_days_ago):
    """Der alte Vorschlag des Dialogs: in den ersten Tagen nach dem Ex-Date 422."""
    ex_date = utcnow().date() - timedelta(days=ex_date_days_ago)

    with pytest.raises(ValidationError) as exc:
        _request(ex_date + timedelta(days=14))

    assert BOOKING_DATE_ERROR in str(exc.value)
