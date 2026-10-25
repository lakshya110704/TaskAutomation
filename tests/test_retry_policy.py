from types import SimpleNamespace

import httplib2
import pytest
import requests
from googleapiclient.errors import HttpError
from slack_sdk.errors import SlackApiError
from tenacity import wait_none
from twilio.base.exceptions import TwilioRestException

from retry import with_retry


def http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} error", response=resp)


def slack_error(status):
    return SlackApiError("slack failed", SimpleNamespace(status_code=status))


def google_error(status):
    return HttpError(httplib2.Response({"status": status}), b"{}")


def twilio_error(status):
    return TwilioRestException(status, "https://api.twilio.com", "twilio failed")


def counted(errors, result="ok"):
    """Return (fn, calls). fn raises each error in order, then returns result."""
    calls = {"n": 0}
    queue = list(errors)

    @with_retry(max_attempts=3)
    def fn():
        calls["n"] += 1
        if queue:
            raise queue.pop(0)
        return result

    return fn.retry_with(wait=wait_none()), calls


def always(error):
    return counted([error] * 10)


@pytest.mark.parametrize(
    "error",
    [requests.ConnectionError("down"), requests.Timeout("slow")],
    ids=["connection", "timeout"],
)
def test_network_errors_retry_then_reraise(error):
    fn, calls = always(error)
    with pytest.raises(type(error)):
        fn()
    assert calls["n"] == 3


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_http_status_is_retried(status):
    fn, calls = always(http_error(status))
    with pytest.raises(requests.HTTPError):
        fn()
    assert calls["n"] == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_error_http_status_is_not_retried(status):
    fn, calls = always(http_error(status))
    with pytest.raises(requests.HTTPError):
        fn()
    assert calls["n"] == 1


def test_fails_twice_then_succeeds():
    fn, calls = counted([requests.ConnectionError(), http_error(503)], result=42)
    assert fn() == 42
    assert calls["n"] == 3


def test_non_api_error_is_not_retried():
    fn, calls = always(ValueError("bad input"))
    with pytest.raises(ValueError):
        fn()
    assert calls["n"] == 1


@pytest.mark.parametrize(
    "make_error, retryable_status, fatal_status",
    [
        (slack_error, 429, 400),
        (google_error, 503, 404),
        (twilio_error, 500, 400),
    ],
    ids=["slack", "google", "twilio"],
)
def test_sdk_errors(make_error, retryable_status, fatal_status):
    fn, calls = always(make_error(retryable_status))
    with pytest.raises(type(make_error(retryable_status))):
        fn()
    assert calls["n"] == 3

    fn, calls = always(make_error(fatal_status))
    with pytest.raises(type(make_error(fatal_status))):
        fn()
    assert calls["n"] == 1


async def test_works_on_async_functions():
    calls = {"n": 0}

    @with_retry(max_attempts=3)
    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("down")
        return "done"

    assert await fn.retry_with(wait=wait_none())() == "done"
    assert calls["n"] == 3

    calls["n"] = 0

    @with_retry(max_attempts=3)
    async def fatal():
        calls["n"] += 1
        raise http_error(400)

    with pytest.raises(requests.HTTPError):
        await fatal.retry_with(wait=wait_none())()
    assert calls["n"] == 1
