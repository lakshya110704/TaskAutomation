### retry.py
# Shared retry policy for outbound calls to third-party APIs (Gemini, Slack,
# Google Calendar, Twilio). Works on both sync and async callables.

import logging

from requests.exceptions import RequestException
from slack_sdk.errors import SlackApiError
from googleapiclient.errors import HttpError
from twilio.base.exceptions import TwilioRestException
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception,
    before_sleep_log,
)

logger = logging.getLogger("retry")

RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RequestException):
        return True
    if isinstance(exc, SlackApiError):
        status = getattr(exc.response, "status_code", None)
        return status in RETRYABLE_HTTP_STATUS
    if isinstance(exc, HttpError):
        return getattr(exc, "status_code", getattr(exc, "resp", None) and exc.resp.status) in RETRYABLE_HTTP_STATUS
    if isinstance(exc, TwilioRestException):
        return exc.status in RETRYABLE_HTTP_STATUS
    return False


def with_retry(max_attempts: int = 3):
    """Retry a flaky third-party API call with exponential backoff + jitter.

    Only retries errors that look transient (timeouts, connection errors,
    429/5xx responses). Anything else — bad input, auth failure, 4xx — fails
    immediately instead of being retried.
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
