import time

from dhanhq import DhanContext, dhanhq
from config import DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN

RETRYABLE_ERRORS = (ConnectionError, ConnectionResetError, TimeoutError, OSError)


def get_dhan_client():
    dhan_context = DhanContext(
        DHAN_CLIENT_ID,
        DHAN_ACCESS_TOKEN
    )

    return dhanhq(dhan_context)


def call_with_retry(fn, *args, retries=3, delay=2, **kwargs):
    """
    Calls a Dhan SDK method, retrying on transient connection errors
    (e.g. ConnectionResetError) so a single dropped socket doesn't feed
    a partial/stale response into the analysis pipeline.
    """

    last_error = None

    for attempt in range(1, retries + 1):

        try:
            return fn(*args, **kwargs)

        except RETRYABLE_ERRORS as ex:
            last_error = ex

            if attempt < retries:
                time.sleep(delay)

    raise ConnectionError(
        f"Dhan API call '{fn.__name__}' failed after {retries} attempts: {last_error}"
    )