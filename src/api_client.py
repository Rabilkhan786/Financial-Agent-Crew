"""This file sends requests to the API.

The Streamlit app uses this file only, so it never needs to know the API's
URL or how to call it directly.
"""

import json

import requests

from src import config

log = config.get_logger(__name__)

# A crew run takes minutes, not seconds - the free tier paces its own calls
# on top of that. A short timeout here would cut off a run that was working.
RUN_TIMEOUT = 900
QUICK_TIMEOUT = 15


class ApiError(Exception):
    """The API could not be reached, or answered with a failure."""


def url_for(path):
    """A URL the Streamlit SERVER can reach. Do not use this for anything
    that ends up in HTML the browser fetches on its own - see chart_url()."""
    return f"{config.API_URL.rstrip('/')}{path}"


def public_url_for(path):
    """A URL the reader's BROWSER can reach. Only chart_url() needs this one."""
    return f"{config.API_PUBLIC_URL.rstrip('/')}{path}"


def health():
    """What the service says about itself. Raises ApiError if it is not there."""
    try:
        response = requests.get(url_for("/health"), timeout=QUICK_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        raise ApiError(f"could not reach the API at {config.API_URL}: {error}")


def stream_analysis(ticker, start_date, end_date):
    """Run one analysis, yielding each event as it arrives.

    Yields dicts: {"event": "progress", ...} while the crew works, then one
    {"event": "result", ...}. An {"event": "error"} is raised as an ApiError so
    the caller has one thing to handle rather than two.
    """
    payload = {"ticker": ticker, "start_date": start_date, "end_date": end_date}
    try:
        with requests.post(url_for("/analyse/stream"), json=payload,
                           stream=True, timeout=RUN_TIMEOUT) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("api_client: could not parse a line: %s", line[:120])
                    continue
                if event.get("event") == "error":
                    raise ApiError(event.get("detail", "the crew failed"))
                yield event
    except requests.RequestException as error:
        raise ApiError(f"the API call failed: {error}")


def fetch_pdf(pdf_url):
    """The finished report as bytes, ready for a download button."""
    try:
        response = requests.get(url_for(pdf_url), timeout=QUICK_TIMEOUT)
        response.raise_for_status()
        return response.content
    except requests.RequestException as error:
        raise ApiError(f"could not fetch the PDF: {error}")


def chart_url(path):
    """A chart path from the API, as something st.image can load.

    Deliberately public_url_for(), not url_for(): this URL goes into an <img>
    tag and is fetched by the reader's browser, not by this server, so it
    needs an address the browser can reach - see API_PUBLIC_URL in config.py.
    """
    return public_url_for(path)
