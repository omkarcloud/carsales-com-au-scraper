"""The /carsales-com-au/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs). Every endpoint caches through
cache.cached_call keyed on the validated params.

Paging. carsales has no page number a request can name: the only way to a
page is the Next button of the page before it, which submits a token. So a
search page is cached as its STATE (cache_config.SEARCH_CACHE): the parsed
results plus the token that asks for the next page. Page N is one request
when page N-1 is cached, which is how a client that follows `next` pages
through a search; a cold jump to page N walks 1..N once and leaves every
page on the way cached. The tokens are stateless on the site's side, so any
thread or pod can replay a cached one. The first page's state also carries
the search form's tokens, which makes/list, models/list and cars/filters
replay to read a filter's options with live counts.

The site serves 20 pages (about 440 cars) per search and no more, whatever
the total: `total_pages` is capped there and `is_truncated` says when the
total is larger than what the pages reach.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from cache import DontCache, cached_call
from scraper_errors import UpstreamError
from carsales_com_au import cache_config as ttl
from carsales_com_au import parsers, refs
from carsales_com_au.fetch import (CarsalesBadRequest, CarsalesNotFound, CarsalesUpstreamError, fetch_details,
                                   fetch_gallery, fetch_postback, fetch_price_guide, fetch_research, fetch_search,
                                   has_price_table, PRICE_TABLE_TRIES)

SIDE_WORKERS = 16       # the photo and price-sheet calls of cars/details run beside the listing call
_side_pool = None
_side_pool_lock = threading.Lock()


# ---- the cached search page ----------------------------------------------------------

def _search_target(filters):
    """(page path, page query) of a search: what the site's own address bar shows."""
    return refs.SEARCH_PATH, refs.search_query(refs.search_expression(**filters), filters.get("sort"))


def _post_body(form, ident, token, tokens, form_token=None):
    body = {"Id": form, "Action": "form:submit", "Data": {ident: {"postBack": token, "newValue": None}},
            "GroupPostBack": tokens.get("group"), "SharedGroupPostBack": tokens.get("shared_group")}
    if form_token:
        body["FormPostBack"] = form_token
    return body


def _search_key(data, page):
    """The cache key of a search page: the filters that are set, the sort
    and the page. Unset filters are left out, so the first page a facet
    endpoint needs is the same row cars/search stores."""
    key = {name: value for name, value in data.items() if value is not None and name != "page"}
    key["page"] = page
    return key


def _page_state(**key):
    """One search page -> parsers.parse_search's record (results + the
    tokens for what comes next). `key` is _search_key's: the filters that
    are set, the sort and the page."""
    page = key["page"]
    filters = {name: value for name, value in key.items() if name != "page"}
    path, query = _search_target(filters)
    if page == 1:
        return parsers.parse_search(fetch_search(path, query))
    previous_key = {**key, "page": page - 1}
    for refresh in (False, True):
        # second round: the cached token was refused, so the page before is fetched again
        previous = _state(previous_key, refresh=refresh)
        cursor = previous.get("cursor")
        if not cursor:
            return {**previous, "page": page, "results": [], "cursor": None, "filter_tokens": None}
        body = _post_body(cursor["form"], cursor["id"], cursor["token"], cursor)
        try:
            state = parsers.parse_search(fetch_postback(cursor["url"], body, path, query, f"search page {page}"))
        except CarsalesBadRequest:
            continue
        if state["page"] == page and (state["results"] or page > _total_pages(previous)):
            return state
        # a wrong page, or a page the search's own total says holds cars served
        # empty (2026-11-14: page 11 of 11 of make=INEOS, 21 cars, once): never
        # cached, asked again from a fresh page before
    raise CarsalesUpstreamError(f"carsales.com.au did not serve page {page} of the search")


def _state(key, refresh=False):
    return cached_call("carsales_com_au.search_page", key, _page_state, ttl.SEARCH_CACHE, refresh=refresh)


def _site_pages(first):
    """Pages the search whose first page is `first` has on the site: its own
    "Page 1 of N", else worked out from the total."""
    site_pages = first.get("site_total_pages")
    if site_pages is None:
        total = first.get("total_count") or 0
        site_pages = -(-total // parsers.PAGE_SIZE) if total else (1 if first.get("results") else 0)
    return site_pages


def _total_pages(first):
    """Pages the site will serve for the search whose first page is `first`."""
    return min(_site_pages(first), parsers.MAX_PAGES)


# ---- cars/search ---------------------------------------------------------------------

def cars_search(**data):
    """Cars for sale that match the filters, 22 per page (the first page of
    the featured order also carries the listings carsales promotes on it)."""
    page = data["page"]
    first = _state(_search_key(data, 1))
    total_pages = _total_pages(first)
    if page == 1:
        state = first
    elif page > total_pages:
        state = {"results": []}          # past the end: an empty page, not an error
    else:
        state = _state(_search_key(data, page))
    return {
        # the uncapped page count: a search without the site's page label is
        # truncated too when its total needs more pages than the site serves
        "is_truncated": _site_pages(first) > total_pages,
        "results": state["results"],
        "pagination": {
            "page": page,
            "items_per_page": parsers.PAGE_SIZE,
            "total_pages": total_pages,
            "total_count": first.get("total_count"),
        },
    }


# ---- makes/list, models/list, cars/filters -------------------------------------------

def _facet(filter_id, filters, drill_into=None):
    """The options of one filter of the search `filters` describes. With
    `drill_into` (an option's name), the options of the level under that
    option instead: a make's models."""
    key = _search_key(filters, 1)
    path, query = _search_target(key)
    last = None
    for refresh in (False, True):
        tokens = _state(key, refresh=refresh).get("filter_tokens") or {}
        item = (tokens.get("filters") or {}).get(filter_id)
        if not item:
            raise CarsalesUpstreamError(f"carsales.com.au's search form has no {filter_id} filter")
        try:
            body = _post_body(item["form"], item["id"], item["token"], tokens, item.get("form_token"))
            facet = parsers.parse_facet(fetch_postback(item["url"], body, path, query, f"{filter_id} options"))
            if drill_into is None:
                return facet
            wanted = drill_into.lower()
            option = next((o for o in facet["options"] if wanted in (o["name"].lower(), o["value"].lower())), None)
            if option is None or not option.get("drill"):
                raise CarsalesNotFound(f"{filter_id.lower()} {drill_into!r} not found")
            drill = option["drill"]
            body = _post_body(item["form"], drill["id"], drill["token"], facet["tokens"], item.get("form_token"))
            under = parsers.parse_facet(fetch_postback(item["url"], body, path, query, f"{drill_into} options"))
            return {**under, "parent": option["name"]}
        except CarsalesBadRequest as e:      # a cached form token the site no longer takes
            last = e
    raise CarsalesUpstreamError(f"carsales.com.au refused the {filter_id} options: {last}")


def _named_options(facet):
    return [{"name": o["name"], "count": o["count"], "is_popular": o["is_popular"]} for o in facet["options"]]


def _makes(condition):
    results = _named_options(_facet(refs.MAKE_FILTER, {"condition": condition}))
    return {"count": len(results), "results": results}


def makes_list(**data):
    """Every make on carsales with its number of cars for sale."""
    return cached_call("carsales_com_au.makes", data, _makes, ttl.FACET_CACHE)


def _models(make, condition):
    facet = _facet(refs.MAKE_FILTER, {"condition": condition}, drill_into=make)
    results = _named_options(facet)
    return {"make": facet["parent"], "count": len(results), "results": results}


def models_list(**data):
    """Every model of a make with its number of cars for sale."""
    return cached_call("carsales_com_au.models", data, _models, ttl.FACET_CACHE)


def _filters(**data):
    name = data["filter"]
    filter_id = refs.FILTERS[name]
    filters = {key: value for key, value in data.items() if key != "filter"}
    facet = _facet(filter_id, filters)
    results = [{"name": o["name"], "value": refs.public_value(name, o["value"]), "count": o["count"],
                "is_selected": o["is_selected"]} for o in facet["options"]]
    return {"filter": name, "count": len(results), "results": results}


def cars_filters(**data):
    """The values one filter can take for the given search, each with the
    number of matching cars; `value` is what cars/search takes for it."""
    return cached_call("carsales_com_au.filters", data, _filters, ttl.FACET_CACHE)


# ---- cars/details --------------------------------------------------------------------

def _pool():
    global _side_pool
    if _side_pool is None:
        with _side_pool_lock:       # two first requests at once must not make two pools
            if _side_pool is None:
                _side_pool = ThreadPoolExecutor(max_workers=SIDE_WORKERS, thread_name_prefix="carsales-com-au-side")
    return _side_pool


def _side(future):
    """A side call's answer, or (None, True) when the site refused it after
    every retry: the listing is still served, without that part, uncached."""
    try:
        return future.result(), False
    except CarsalesNotFound:
        return None, False
    except UpstreamError as e:
        print(f"carsales-com-au: listing side call failed: {e}")
        return None, True


def _sheet_has_table(record):
    """Whether the site keeps a price table for this listing. A dealer's car
    priced "indicative drive away" (carsales' own estimate: the dealer gave
    no drive-away price) never has one: 1,156 of 1,156 on 2026-11-14, on the
    AWS gateway, AU datacenter and AU residential exits alike. Every other
    dealer and private listing has one; a showroom car priced that way has
    it for most makes (3,290 of 4,154), so it is asked again."""
    price = record.get("price") or {}
    seller = record.get("seller") or {}
    return not ((price.get("type") or "").startswith("indicative") and seller.get("type") == "dealer")


def _details(car):
    # the photos and the price sheet are their own calls on the site; they
    # run beside the listing call, each on its worker's own session. The
    # sheet is asked once there: whether a sheet without its table is worth
    # asking again depends on the listing
    gallery_call = _pool().submit(fetch_gallery, car)
    price_call = _pool().submit(fetch_price_guide, car, 1)
    try:
        record = parsers.parse_details(fetch_details(car), car)
    except Exception:
        gallery_call.cancel()
        price_call.cancel()
        raise
    gallery, gallery_failed = _side(gallery_call)
    sheet, sheet_failed = _side(price_call)
    if sheet and not has_price_table(sheet) and _sheet_has_table(record):
        sheet, sheet_failed = _side(_pool().submit(fetch_price_guide, car, PRICE_TABLE_TRIES - 1))
        if sheet and not has_price_table(sheet):
            sheet_failed = True         # served without its breakdown, not cached: the next ask tries again
    media = parsers.parse_gallery(gallery) if gallery else {"images": [], "videos": []}
    if media["images"]:
        record["images"] = media["images"]
        record["image_count"] = max(record.get("image_count") or 0, len(media["images"]))
    record["videos"] = media["videos"]
    record["price"]["breakdown"] = parsers.parse_price_guide(sheet) or None if sheet else None
    return DontCache(record) if gallery_failed or sheet_failed else record


def car_details(**data):
    """One listing in full: the car, its price with the on-road cost
    breakdown, location, seller, description, every feature and
    specification, and every photo."""
    return cached_call("carsales_com_au.details", data, _details, ttl.DETAILS_CACHE)


# ---- models/details ------------------------------------------------------------------

def _model(make, model, year):
    make_slug, model_slug = refs.slugify(make), refs.slugify(model)
    if not make_slug or not model_slug:
        # a name without a letter or digit ("--", "日産") has no page: asking
        # would be for /research//<model>/, another page's path
        raise CarsalesNotFound(f"model {make} {model} not found")
    payload = fetch_research(make_slug, model_slug, year)
    return parsers.parse_research(payload)


def model_details(**data):
    """carsales' research page of a model year: the indicative price range,
    body / fuel / seat options, every badge, the price range of every model
    year, FAQ and the lead expert review."""
    return cached_call("carsales_com_au.model", data, _model, ttl.RESEARCH_CACHE)
