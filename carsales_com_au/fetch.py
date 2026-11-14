"""carsales.com.au transport: plain curl_cffi on the site's own JSON calls.
No browser, no login, no cookies. Egress: one session per thread on the
exit config.CARSALES_COM_AU_EXIT names (egress.exit_session): in production
the Australian gateway exit ("gateway:au", a fresh Australian address per
request). A retryable failure drops the session, so the retry rides a fresh
exit.

The site sits behind DataDome. Its HTML pages are refused on most exits and
any URL with an `offset=` parameter on all of them, but the JSON calls its
own front end makes pass the gateway exit untouched (pod probe 2026-11-12,
table in config.py). The front end is a server-driven UI ("merlin"): every
call answers a component tree ({root | partials, metaData}), which
parsers.py reads.

Six upstream surfaces:

  * SEARCH   POST /_api/search-core/cars/?q=<expr>&sort=<sort>   body {}
    The first page of a search (refs.search_query builds the query). An
    unknown make / model / region is not an error: the answer is a page with
    0 results. A malformed expression answers HTTP 404.

  * POSTBACK POST /_api/search-core/?event=<event>   body {Id, Action, Data,
    GroupPostBack, SharedGroupPostBack}
    What the site's forms submit: the next page of a search
    (event=search-pagination-changed, Data = the Next button's token) and a
    filter's value list (event=search-refinements-changing, sent to
    /_api/search-core-refinements/ like the site does). The tokens come from
    the previous answer and are stateless: they replay from any session and
    address (measured 28 minutes after they were issued, 2026-11-12). The
    two group tokens carry the search itself; without them the site answers
    the same event for an unfiltered search.

  * DETAILS  POST /_api/details-core/cars/details/x/<id>/   body {}
    One listing. The page is named by the `x-csn-request-path` header, not
    by the URL (without the header every id answers 404); the slug segment
    is ignored by the site. An unknown id answers HTTP 404.

  * GALLERY  GET /_api/gallery-core/<id>/
    Every photo of the listing at full size (the listing answer carries
    only the first four).

  * PRICE    GET /_details/api/v1/price-guide/carsales/<id>
    The small HTML sheet behind a listing's price link: the price before
    government charges, stamp duty, transfer fee, drive-away price.

  * RESEARCH GET /_api/taco-makemodel/research/<make>/<model>/[<year>/]
    The model research page as JSON. An unknown make / model / year answers
    HTTP 404.

Every header that matters is here: `x-csn-request-path` /
`x-csn-request-query` (the page the call belongs to) and the two breakpoint
headers (the answer then carries one layout instead of two).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  CarsalesUpstreamError  transport failure / 5xx / unparseable   — retryable
  CarsalesBlocked        403 / 429 / a DataDome page              — retryable on a fresh exit
  CarsalesBadRequest     the site refused the search expression   — never retried
  CarsalesNotFound       unknown listing / model                  — never retried
"""
import os
import sys
import threading
import time

# Allow direct execution (python carsales_com_au/fetch.py): flat imports
# resolve like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
import fastjson
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from carsales_com_au.refs import SITE, listing_path, research_path

IMPERSONATE = "chrome"
# A gateway exit request gets 29 s in all; answers take 0.5-3 s, so a hung
# request is cut early and retried on a fresh exit.
API_TIMEOUT = 20
PRICE_TIMEOUT = 12

SEARCH_API = "/_api/search-core"
REFINEMENTS_API = "/_api/search-core-refinements"
DETAILS_API = "/_api/details-core"
RESEARCH_API = "/_api/taco-makemodel"
GALLERY_API = "/_api/gallery-core"
PRICE_GUIDE_PATH = "/_details/api/v1/price-guide/carsales/"
PRICE_TABLE_TRIES = 4    # a sheet without its price table is asked again, up to this many answers in all

BREAKPOINT = "wide"
JSON_HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "adaptive-breakpoint": BREAKPOINT,
    "x-csn-breakpoint": BREAKPOINT,
    "origin": SITE,
}
# The price sheet is HTML, but it must be asked for like the fetch() the page
# makes: with a navigation `accept` (text/html,...) DataDome refuses it on
# the gateway exit (3/3 x 403 against 3/3 x 200 with */*, 2026-11-12).
SHEET_HEADERS = {"accept": "*/*"}

# DataDome's interstitial, whatever status it comes with.
_BLOCK_MARKERS = ("captcha-delivery.com", "var dd={", "Please enable JS and disable any ad blocker")


class CarsalesUpstreamError(UpstreamError):
    """Transport failure, 5xx, or an answer that is not the expected JSON — retryable."""


class CarsalesBlocked(CarsalesUpstreamError, Blocked):
    """403 / 429 or a DataDome page — retried on a fresh exit."""


class CarsalesBadRequest(BadRequest):
    """The site refused the search expression — never retried."""


class CarsalesNotFound(NotFound):
    """No such listing / model page — never retried."""


# ---- sessions ------------------------------------------------------------------------

# One curl session per cheroot worker thread (a curl handle must not be
# shared across threads). Nothing else lives here: the paging tokens are
# data, kept in the response cache (api.py).
_local = threading.local()


# Two lanes, each its own exit knob: "site" (search, listing, photos, research:
# config.CARSALES_COM_AU_EXIT) and "price" (the price sheet:
# config.CARSALES_COM_AU_PRICE_EXIT), see has_price_table.
_EXITS = {"site": "CARSALES_COM_AU_EXIT", "price": "CARSALES_COM_AU_PRICE_EXIT"}


def _session(lane="site"):
    attr = "session_" + lane
    sess = getattr(_local, attr, None)
    if sess is None:
        sess = egress.exit_session(getattr(config, _EXITS[lane]), impersonate=IMPERSONATE)
        setattr(_local, attr, sess)
    if getattr(sess, "via_exit_gateway", False):
        # Every gateway request leaves from a new address: a DataDome cookie
        # earned by the last one would arrive from the wrong address. No call
        # needs a cookie, so each goes out without the ones the site set.
        sess.cookies.clear()
    return sess


def _drop_session(lane="site"):
    """Close the thread's session of `lane` so the retry rides a fresh exit."""
    attr = "session_" + lane
    sess = getattr(_local, attr, None)
    setattr(_local, attr, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _retrying(fn, label, lane="site"):
    """Run fn() under the shared retry policy (CarsalesUpstreamError only,
    Blocked included, each retry on a fresh session / exit of `lane`;
    BadRequest and NotFound surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except CarsalesUpstreamError as e:
            last = e
            _drop_session(lane)
        print(f"carsales-com-au: {label} attempt {attempt}/{config.MAX_RETRIES} failed: {last}")
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def looks_blocked(text):
    head = (text or "")[:4000]
    return any(marker in head for marker in _BLOCK_MARKERS)


def _classify(resp, label, not_found=CarsalesNotFound, missing=(404,)):
    """Map an HTTP response to the error taxonomy; return the body text.
    `not_found` is what a status in `missing` means for this surface."""
    status = resp.status_code
    text = resp.text
    if status in (401, 403, 429) or looks_blocked(text):
        raise CarsalesBlocked(f"HTTP {status} (anti-bot page) for {label}")
    if status in missing:
        raise not_found(f"{label} not found" if not_found is CarsalesNotFound
                        else f"carsales.com.au refused {label}")
    if status != 200:
        raise CarsalesUpstreamError(f"HTTP {status} for {label}")
    return text


def _request(method, path, label, *, headers, body=None, timeout=API_TIMEOUT, not_found=CarsalesNotFound,
             missing=(404,), lane="site"):
    def once():
        try:
            resp = _session(lane).request(method, SITE + path, headers=headers, data=body, timeout=timeout)
        except Exception as e:
            raise CarsalesUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        return _classify(resp, label, not_found, missing)
    return once


def _json(text, label):
    try:
        payload = fastjson.loads(text)
    except ValueError:
        raise CarsalesUpstreamError(f"non-JSON answer for {label}: {text[:120]!r}")
    if not isinstance(payload, dict):
        raise CarsalesUpstreamError(f"unexpected answer shape for {label}")
    return payload


def _call(method, path, label, *, page_path, page_query="", body=None, not_found=CarsalesNotFound):
    """One JSON call of the site's front end -> the decoded component tree."""
    headers = {**JSON_HEADERS, "x-csn-request-path": page_path, "x-csn-request-query": page_query,
               "referer": SITE + page_path + page_query}
    if method == "GET":
        headers.pop("content-type")
    send = _request(method, path, label, headers=headers, body=body, not_found=not_found)

    def once():
        return _json(send(), label)
    return _retrying(once, label)


# ---- the six surfaces ---------------------------------------------------------------

def fetch_search(page_path, page_query):
    """The first page of a search -> {root, metaData, partials, ...}."""
    return _call("POST", SEARCH_API + page_path + page_query, "search", page_path=page_path,
                 page_query=page_query, body="{}", not_found=CarsalesBadRequest)


def fetch_postback(post_back_url, body, page_path, page_query, label):
    """Submit one of the search page's forms (`post_back_url` is the form's
    own "/?event=..." target) -> {metaData, partials, ...}."""
    api = REFINEMENTS_API if ("event=search-refinements" in post_back_url
                              or "group=refinements" in post_back_url) else SEARCH_API
    return _call("POST", api + post_back_url, label, page_path=page_path, page_query=page_query,
                 body=fastjson.dumps(body), not_found=CarsalesBadRequest)


def is_listing(payload):
    """True when an answer is a listing page: it names the listing in its
    metadata. The site's "page not found" tree, and what a withdrawn id
    redirects to, do not."""
    for entry in (payload or {}).get("metaData") or []:
        if not isinstance(entry, dict):
            continue
        key, value = entry.get("key"), str(entry.get("value") or "")
        if key == "tracking/page/details/networkid" and value:
            return True
        if key == "page/canonical-url" and "/details/" in value:
            return True
    return False


def fetch_details(listing_id):
    """One listing -> {root, metaData, partials, ...}. NotFound for an id the
    site does not know (HTTP 404) and for an answer without the listing's
    metadata (what a withdrawn id redirects to)."""
    path = listing_path(listing_id)
    label = f"listing {listing_id}"
    payload = _call("POST", DETAILS_API + path, label, page_path=path, body="{}")
    if not is_listing(payload):
        raise CarsalesNotFound(f"{label} not found")
    return payload


def fetch_gallery(listing_id):
    """Every photo (and video) of a listing -> {root, partials, ...}."""
    return _call("GET", f"{GALLERY_API}/{listing_id}/", f"photos of {listing_id}",
                 page_path=listing_path(listing_id))


def fetch_price_guide(listing_id):
    """The listing's price sheet (HTML), or None when the site has none for
    it. For an id it does not know this path answers HTTP 500, every time
    (2026-11-12), so a 500 here means "no sheet" and is not retried. It rides
    its own exit (config.CARSALES_COM_AU_PRICE_EXIT): see has_price_table."""
    label = f"price guide {listing_id}"
    send = _request("GET", PRICE_GUIDE_PATH + listing_id, label,
                    headers={**SHEET_HEADERS, "referer": SITE + listing_path(listing_id)}, timeout=PRICE_TIMEOUT,
                    missing=(404, 500), lane="price")
    try:
        sheet = _retrying(send, label, lane="price")
        for _ in range(PRICE_TABLE_TRIES - 1):
            if not sheet or has_price_table(sheet):
                break
            # served without its table: ask again from a fresh exit
            _drop_session("price")
            sheet = _retrying(send, label, lane="price")
    except CarsalesNotFound:
        return None
    if sheet and not has_price_table(sheet):
        print(f"carsales-com-au: {label} came back without its price table {PRICE_TABLE_TRIES} times "
              "(carsales sends it to Australian home connections: outside Australia or on a cloud server, "
              "set CARSALES_COM_AU_PRICE_PROXY or CARSALES_COM_AU_PROXY to an Australian residential proxy)")
    return sheet


def has_price_table(sheet):
    """The site sends some callers the price sheet with its notes only, no
    table, and then the breakdown is empty. It goes by the caller's address
    (measured 2026-11-14): AU residential exits 8/8 with the table; the
    Sydney AWS gateway 847/1,000 at a light load, then about 1 in 8 while
    ~20 requests/s were going through it (plus a 403); an Indian home IP
    1 in 6. Same SYD CloudFront edge, every answer a cache miss."""
    return 'class="entry' in sheet


def fetch_research(make_slug, model_slug, year=None):
    """The model research page as JSON -> {root, metaData, ...}."""
    path = research_path(make_slug, model_slug, year)
    label = f"model {make_slug}/{model_slug}" + (f"/{year}" if year else "")
    return _call("GET", RESEARCH_API + path, label, page_path=path)
