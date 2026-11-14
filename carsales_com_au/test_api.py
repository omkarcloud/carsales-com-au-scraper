"""Offline tests for the endpoint logic in carsales_com_au/api.py: the
token-driven paging, the facet calls and the listing merge, with the
transport and the cache replaced by fakes (the answers are the fixtures).

    python -m pytest carsales_com_au/test_api.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cache import DontCache  # noqa: E402
from carsales_com_au import api, fetch, parsers, schemas  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def fixture(name):
    return json.loads(raw(name))


class FakeCache:
    """cache.cached_call's contract in memory: keyed on (namespace, params),
    DontCache results returned but not stored, refresh overwrites."""

    def __init__(self):
        self.rows = {}

    def __call__(self, namespace, data, fn, ttl, cache=True, refresh=False):
        key = (namespace, json.dumps(data, sort_keys=True))
        if not refresh and key in self.rows:
            return self.rows[key]
        result = fn(**data)
        if isinstance(result, DontCache):
            return result.data
        self.rows[key] = result
        return result


@pytest.fixture
def cache(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(api, "cached_call", fake)
    return fake


def _search_params(**params):
    return schemas.CarsSearchSchema().load(params)


class Site:
    """The search surfaces: a first page, and postbacks that only accept
    the token of the page before."""

    def __init__(self, monkeypatch, first="search_corolla_page1.json", pages=None, refuse_tokens=()):
        self.first = fixture(first)
        self.pages = pages or {}
        self.refuse = set(refuse_tokens)
        self.searches = []
        self.postbacks = []
        monkeypatch.setattr(api, "fetch_search", self.fetch_search)
        monkeypatch.setattr(api, "fetch_postback", self.fetch_postback)

    def fetch_search(self, path, query):
        self.searches.append((path, query))
        return self.first

    def fetch_postback(self, url, body, path, query, label):
        self.postbacks.append((url, body, path, query))
        token = next(iter(body["Data"].values()))["postBack"]
        if token in self.refuse:
            self.refuse.discard(token)
            raise fetch.CarsalesBadRequest("carsales.com.au refused search")
        return self.pages[len([p for p in self.postbacks if "pagination" in p[0]]) + 1]


# ---- cars/search ---------------------------------------------------------------------

def test_first_page(monkeypatch, cache):
    site = Site(monkeypatch)
    out = api.cars_search(**_search_params(make="Toyota", model="Corolla"))
    assert site.searches == [("/cars/", "?q=(And.Make.Toyota._.Model.Corolla.)")]
    assert out["pagination"] == {"page": 1, "items_per_page": 22, "total_pages": 20, "total_count": 1966}
    assert out["is_truncated"] is True          # 90 pages on the site, 20 served
    assert len(out["results"]) == 28
    assert "cursor" not in out and "filter_tokens" not in out
    assert "b64:" not in json.dumps(out)        # no token ever reaches a caller


def test_second_page_replays_the_next_token(monkeypatch, cache):
    site = Site(monkeypatch, pages={2: fixture("search_corolla_price_page2.json")})
    params = _search_params(make="Toyota", model="Corolla", sort="price_low_to_high", page=2)
    out = api.cars_search(**params)
    assert len(site.searches) == 1 and len(site.postbacks) == 1
    url, body, path, query = site.postbacks[0]
    first = parsers.parse_search(site.first)
    assert url == "/?event=search-pagination-changed"
    assert (path, query) == ("/cars/", "?q=(And.Make.Toyota._.Model.Corolla.)&sort=~Price")
    assert body == {"Id": "pagination-form", "Action": "form:submit",
                    "Data": {"search-pagination": {"postBack": first["cursor"]["token"], "newValue": None}},
                    "GroupPostBack": first["cursor"]["group"],
                    "SharedGroupPostBack": first["cursor"]["shared_group"]}
    assert out["pagination"]["page"] == 2 and len(out["results"]) == 22
    # the page is cached: asking again costs nothing
    api.cars_search(**params)
    assert len(site.searches) == 1 and len(site.postbacks) == 1


def test_page_after_a_cached_page_is_one_request(monkeypatch, cache):
    page2 = fixture("search_corolla_price_page2.json")
    site = Site(monkeypatch, pages={2: page2, 3: _renumber(page2, 3)})
    params = _search_params(make="Toyota", model="Corolla", sort="price_low_to_high")
    api.cars_search(**{**params, "page": 2})
    assert len(site.postbacks) == 1
    out = api.cars_search(**{**params, "page": 3})
    assert len(site.searches) == 1 and len(site.postbacks) == 2
    sent = next(iter(site.postbacks[1][1]["Data"].values()))["postBack"]
    assert sent == parsers.parse_search(page2)["cursor"]["token"]      # page 2's own Next token
    assert out["pagination"]["page"] == 3


def _renumber(payload, page):
    """The same postback answer claiming to be `page`."""
    copy = json.loads(json.dumps(payload))
    for entry in copy["metaData"]:
        if entry.get("key") == "tracking/page/pageNumber":
            entry["value"] = str(page)
    return copy


def test_cold_jump_walks_and_caches_every_page(monkeypatch, cache):
    page2 = fixture("search_corolla_price_page2.json")
    site = Site(monkeypatch, pages={n: _renumber(page2, n) for n in range(2, 6)})
    params = _search_params(make="Toyota", model="Corolla", sort="price_low_to_high", page=5)
    assert api.cars_search(**params)["pagination"]["page"] == 5
    assert len(site.searches) == 1 and len(site.postbacks) == 4
    api.cars_search(**{**params, "page": 3})                 # already on the way
    assert len(site.postbacks) == 4


def test_refused_token_refetches_the_page_before(monkeypatch, cache):
    page2 = fixture("search_corolla_price_page2.json")
    stale = parsers.parse_search(fixture("search_corolla_page1.json"))["cursor"]["token"]
    site = Site(monkeypatch, pages={2: page2, 3: page2}, refuse_tokens=[stale])
    out = api.cars_search(**_search_params(make="Toyota", model="Corolla", page=2))
    # refused once -> page 1 fetched again -> its token replayed
    assert len(site.searches) == 2 and len(site.postbacks) == 2
    assert out["pagination"]["page"] == 2 and len(out["results"]) == 22


def test_answer_for_the_wrong_page_is_an_upstream_error(monkeypatch, cache):
    page2 = fixture("search_corolla_price_page2.json")
    Site(monkeypatch, pages={n: page2 for n in range(2, 9)})      # always says "page 2"
    with pytest.raises(fetch.CarsalesUpstreamError) as e:
        api.cars_search(**_search_params(make="Toyota", model="Corolla", page=3))
    assert "page 3" in str(e.value)


def _empty_page(parse, page, times):
    """parsers.parse_search, except that `page` comes back without cars the first `times` times."""
    served = []

    def wrapped(payload):
        state = parse(payload)
        if state["page"] == page and len(served) < times:
            served.append(1)
            return {**state, "results": [], "cursor": None}
        return state
    return wrapped


def test_in_range_page_served_empty_is_asked_again(monkeypatch, cache):
    page2 = fixture("search_corolla_price_page2.json")
    site = Site(monkeypatch, pages={2: page2, 3: page2})
    monkeypatch.setattr(parsers, "parse_search", _empty_page(parsers.parse_search, 2, times=1))
    out = api.cars_search(**_search_params(make="Toyota", model="Corolla", page=2))
    assert len(out["results"]) == 22 and len(site.postbacks) == 2


def test_in_range_page_always_empty_is_an_upstream_error_not_cached(monkeypatch, cache):
    page2 = fixture("search_corolla_price_page2.json")
    Site(monkeypatch, pages={n: page2 for n in range(2, 9)})
    monkeypatch.setattr(parsers, "parse_search", _empty_page(parsers.parse_search, 2, times=99))
    with pytest.raises(fetch.CarsalesUpstreamError) as e:
        api.cars_search(**_search_params(make="Toyota", model="Corolla", page=2))
    assert "page 2" in str(e.value)
    assert not [k for k in cache.rows if '"page": 2' in k[1]]


def test_page_past_the_end_is_empty_and_costs_no_postback(monkeypatch, cache):
    small = _renumber(fixture("search_small_last_page.json"), 1)       # a 2-page search (27 cars)
    site = Site(monkeypatch)
    site.first = small
    monkeypatch.setattr(parsers, "parse_search", _as_first_of_two(parsers.parse_search))
    out = api.cars_search(**_search_params(make="Toyota", model="Corolla", colour="orange", page=7))
    assert out["results"] == [] and site.postbacks == []
    assert out["pagination"] == {"page": 7, "items_per_page": 22, "total_pages": 2, "total_count": 27}
    assert out["is_truncated"] is False


def _as_first_of_two(parse):
    def wrapped(payload):
        state = parse(payload)
        return {**state, "page": 1, "site_total_pages": 2}
    return wrapped


def test_no_results(monkeypatch, cache):
    Site(monkeypatch, first="search_no_results.json")
    out = api.cars_search(**_search_params(make="Ferrari", max_price=5000))
    assert out == {"is_truncated": False, "results": [],
                   "pagination": {"page": 1, "items_per_page": 22, "total_pages": 0, "total_count": 0}}


def test_truncated_without_the_site_page_label(monkeypatch, cache):
    """A first page without "Page 1 of N": the page count comes from the
    total, and a total past the site's 20 pages is still reported truncated."""
    Site(monkeypatch)
    parse = parsers.parse_search
    monkeypatch.setattr(parsers, "parse_search", lambda payload: {**parse(payload), "site_total_pages": None})
    out = api.cars_search(**_search_params(make="Toyota", model="Corolla"))
    assert out["pagination"]["total_pages"] == 20 and out["pagination"]["total_count"] == 1966
    assert out["is_truncated"] is True


def test_search_key_ignores_unset_filters():
    assert api._search_key({"make": "Toyota", "model": None, "sort": None, "page": 4}, 1) == {"make": "Toyota", "page": 1}
    assert api._search_key({"condition": None}, 1) == {"page": 1}


# ---- makes/list, models/list, cars/filters -------------------------------------------

class FacetSite(Site):
    def __init__(self, monkeypatch, answers):
        super().__init__(monkeypatch)
        self.answers = list(answers)

    def fetch_postback(self, url, body, path, query, label):
        self.postbacks.append((url, body, path, query))
        return self.answers.pop(0)


def test_makes_list(monkeypatch, cache):
    site = FacetSite(monkeypatch, [fixture("facet_makes.json")])
    out = api.makes_list(condition=None)
    assert out["count"] == 147 == len(out["results"])
    assert out["results"][0] == {"name": "Abarth", "count": 75, "is_popular": False}
    assert {"name": "Toyota", "count": 23186, "is_popular": True} in out["results"]
    url, body, path, query = site.postbacks[0]
    tokens = parsers.parse_search(site.first)["filter_tokens"]
    assert url == "/?event=search-refinements-changing&group=refinements" and (path, query) == ("/cars/", "")
    assert body["Id"] == "search-refinements-form"
    assert body["Data"] == {"drill-down-Make": {"postBack": tokens["filters"]["Make"]["token"], "newValue": None}}
    assert body["GroupPostBack"] == tokens["group"]
    api.makes_list(condition=None)
    assert len(site.postbacks) == 1                      # cached


def test_makes_list_shares_the_first_page_with_search(monkeypatch, cache):
    site = FacetSite(monkeypatch, [fixture("facet_makes.json")])
    api.cars_search(**_search_params())
    api.makes_list(condition=None)
    assert len(site.searches) == 1


def test_models_list_drills_into_the_make(monkeypatch, cache):
    site = FacetSite(monkeypatch, [fixture("facet_makes.json"), fixture("facet_models_toyota.json")])
    out = api.models_list(make="toyota", condition=None)
    assert out["make"] == "Toyota" and out["count"] == 81
    assert {"name": "Corolla", "count": 1967, "is_popular": True} in out["results"]
    makes = parsers.parse_facet(fixture("facet_makes.json"))
    toyota = next(o for o in makes["options"] if o["name"] == "Toyota")
    second = site.postbacks[1][1]
    assert second["Data"] == {"drill-down-Toyota": {"postBack": toyota["drill"]["token"], "newValue": None}}
    assert second["GroupPostBack"] == makes["tokens"]["group"]      # the make list's own state, not the page's


def test_models_list_unknown_make_is_not_found(monkeypatch, cache):
    FacetSite(monkeypatch, [fixture("facet_makes.json")])
    with pytest.raises(fetch.CarsalesNotFound) as e:
        api.models_list(make="Toyotaa", condition=None)
    assert str(e.value) == "make 'Toyotaa' not found"


def test_cars_filters(monkeypatch, cache):
    site = FacetSite(monkeypatch, [fixture("facet_body_type.json"), fixture("facet_state.json")])
    params = schemas.CarsFiltersSchema().load({"filter": "body_type", "make": "Toyota"})
    out = api.cars_filters(**params)
    assert out["filter"] == "body_type" and out["count"] == 12
    assert out["results"][1] == {"name": "Cab Chassis", "value": "cab_chassis", "count": 6828, "is_selected": False}
    assert site.searches == [("/cars/", "?q=(And.Make.Toyota.)")]
    assert list(site.postbacks[0][1]["Data"]) == ["drill-down-BodyStyle"]
    # every value can be passed back to cars/search
    for row in out["results"]:
        schemas.CarsSearchSchema().load({"body_type": row["value"]})
    states = api.cars_filters(**schemas.CarsFiltersSchema().load({"filter": "state", "make": "Toyota"}))
    assert [r["value"] for r in states["results"]] == ["act", "nsw", "nt", "qld", "sa", "tas", "vic", "wa"]
    assert states["results"][1]["name"] == "NSW"


def test_refused_form_token_refetches_the_first_page(monkeypatch, cache):
    site = FacetSite(monkeypatch, [fixture("facet_makes.json")])
    calls = {"n": 0}
    answer = site.fetch_postback

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise fetch.CarsalesBadRequest("carsales.com.au refused Make options")
        return answer(*args)
    monkeypatch.setattr(api, "fetch_postback", flaky)
    assert api.makes_list(condition=None)["count"] == 147
    assert len(site.searches) == 2


# ---- cars/details --------------------------------------------------------------------

def _listing(monkeypatch, gallery=None, sheet=None, details="details_dealer_used.json"):
    calls = []

    def side(name, value):
        def call(car):
            calls.append((name, car))
            if isinstance(value, Exception):
                raise value
            return value
        return call
    monkeypatch.setattr(api, "fetch_details", lambda car: calls.append(("details", car)) or fixture(details))
    monkeypatch.setattr(api, "fetch_gallery", side("gallery", gallery))
    monkeypatch.setattr(api, "fetch_price_guide", side("price", sheet))
    return calls


def test_car_details_merges_photos_and_price_sheet(monkeypatch, cache):
    calls = _listing(monkeypatch, fixture("gallery_dealer_used.json"), raw("price_guide_dealer.html"))
    out = api.car_details(car="OAG-AD-26091046")
    assert sorted(calls) == [("details", "OAG-AD-26091046"), ("gallery", "OAG-AD-26091046"),
                             ("price", "OAG-AD-26091046")]
    assert out["id"] == "OAG-AD-26091046"
    assert len(out["images"]) == 26 == out["image_count"] and out["videos"] == []
    assert [row["kind"] for row in out["price"]["breakdown"]] == ["base", "charge", "charge", "total"]
    assert out["price"]["breakdown"][-1]["amount"] == out["price"]["amount"] == 26990
    api.car_details(car="OAG-AD-26091046")
    assert len(calls) == 3                               # cached


def test_car_details_without_side_answers_is_served_but_not_cached(monkeypatch, cache):
    calls = _listing(monkeypatch, fetch.CarsalesBlocked("HTTP 403"), fetch.CarsalesUpstreamError("timeout"))
    out = api.car_details(car="OAG-AD-26091046")
    assert len(out["images"]) == 4 and out["image_count"] == 26      # the listing's own first photos
    assert out["price"]["breakdown"] is None and out["price"]["amount"] == 26990
    assert cache.rows == {}
    api.car_details(car="OAG-AD-26091046")
    assert len(calls) == 6                               # tried again


def test_car_details_listing_without_price_sheet_is_cached(monkeypatch, cache):
    _listing(monkeypatch, fixture("gallery_dealer_used.json"), None)       # fetch_price_guide: None on 404
    out = api.car_details(car="OAG-AD-26091046")
    assert out["price"]["breakdown"] is None and len(cache.rows) == 1


def test_car_details_price_sheet_without_its_table_is_served_but_not_cached(monkeypatch, cache):
    # the site sometimes answers the sheet with its notes only: no breakdown,
    # and the listing is not cached so the next ask tries the sheet again
    _listing(monkeypatch, fixture("gallery_dealer_used.json"), raw("price_guide_no_table.html"))
    out = api.car_details(car="OAG-AD-26091046")
    assert out["price"]["breakdown"] is None and out["images"]
    assert cache.rows == {}


def test_car_details_unknown_listing(monkeypatch, cache):
    _listing(monkeypatch, fetch.CarsalesNotFound("photos not found"), None)

    def missing(car):
        raise fetch.CarsalesNotFound(f"listing {car} not found")
    monkeypatch.setattr(api, "fetch_details", missing)
    with pytest.raises(fetch.CarsalesNotFound) as e:
        api.car_details(car="OAG-AD-99999999")
    assert str(e.value) == "listing OAG-AD-99999999 not found"
    assert cache.rows == {}


# ---- models/details ------------------------------------------------------------------

def test_model_details(monkeypatch, cache):
    asked = []
    monkeypatch.setattr(api, "fetch_research",
                        lambda make, model, year: asked.append((make, model, year)) or fixture("research_corolla_2020.json"))
    out = api.model_details(make="Toyota", model="Corolla", year=2020)
    assert asked == [("toyota", "corolla", 2020)]
    assert out["year"] == 2020 and out["badges_count"] == 17
    api.model_details(make="Mercedes-Benz", model="A Class", year=None)
    assert asked[-1] == ("mercedes-benz", "a-class", None)


def test_model_details_name_without_a_slug_is_not_found(monkeypatch, cache):
    asked = []
    monkeypatch.setattr(api, "fetch_research", lambda *args: asked.append(args) or {})
    with pytest.raises(fetch.CarsalesNotFound):
        api.model_details(make="--", model="Corolla", year=None)
    with pytest.raises(fetch.CarsalesNotFound):
        api.model_details(make="Toyota", model="日産", year=None)
    assert asked == [] and cache.rows == {}


# ---- the price sheet's missing table -------------------------------------------------

def test_price_sheet_without_its_table_is_asked_again(monkeypatch):
    answers = [raw("price_guide_no_table.html"), raw("price_guide_no_table.html"), raw("price_guide_dealer.html")]
    asked, dropped = [], []
    monkeypatch.setattr(fetch, "_request", lambda *a, **k: lambda: asked.append(1) or answers[len(asked) - 1])
    monkeypatch.setattr(fetch, "_drop_session", lambda: dropped.append(1))
    sheet = fetch.fetch_price_guide("OAG-AD-26091046")
    assert fetch.has_price_table(sheet) and len(asked) == 3 and len(dropped) == 2


def test_price_sheet_never_with_its_table_stops_after_the_tries(monkeypatch):
    asked = []
    monkeypatch.setattr(fetch, "_request", lambda *a, **k: lambda: asked.append(1) or raw("price_guide_no_table.html"))
    monkeypatch.setattr(fetch, "_drop_session", lambda: None)
    sheet = fetch.fetch_price_guide("OAG-AD-26091046")
    assert not fetch.has_price_table(sheet) and len(asked) == fetch.PRICE_TABLE_TRIES
    assert parsers.parse_price_guide(sheet) == []
