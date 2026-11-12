"""Live endpoint smoke tests: one call per /carsales-com-au/* route against a
running service, with example values proven to return data (2026-11-12,
through the local route layer on the gateway exit). The listing tooling
reads the first call per path as that route's working example.

Skipped unless CARSALES_COM_AU_BASE points at a running service:

    python run.py                                          # standalone: http://127.0.0.1:8000
    ONLY_SCRAPER=carsales-com-au python run.py --dev       # inside the scrapers service: :6002
    CARSALES_COM_AU_BASE=http://127.0.0.1:8000 python -m pytest carsales_com_au/test_endpoints.py -q

A listing is sold sooner or later: when /cars/details answers 404 for the
example below, pick a current one from /cars/search.
"""
import os

import pytest

BASE = os.environ.get("CARSALES_COM_AU_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set CARSALES_COM_AU_BASE to run live endpoint tests")

SHELBY_GT500 = "OAG-AD-26356625"      # a 2020 Ford Mustang Shelby GT500 at a Melbourne dealer


def call(path, status=200, **params):
    from curl_cffi import requests
    # the full route path: the scrapers service serves it, and the standalone kit mounts it too
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_car_details():
    car = call("/carsales-com-au/cars/details", car="OAG-AD-26356625")
    assert car["id"] == SHELBY_GT500 and car["make"] == "Ford" and car["model"] == "Mustang"
    assert car["price"]["amount"] and car["price"]["currency"] == "AUD" and car["price"]["breakdown"]
    assert car["location"]["state"] and car["location"]["postcode"]
    assert car["specifications"] and len(car["images"]) > 4
    linked = call("/carsales-com-au/cars/details",
                  car=f"https://www.carsales.com.au/cars/details/2020-ford-mustang-shelby-gt500-auto-rwd/{SHELBY_GT500}/")
    assert linked["id"] == SHELBY_GT500
    call("/carsales-com-au/cars/details", status=404, car="OAG-AD-99999999")
    call("/carsales-com-au/cars/details", status=400, car="26356625")


def test_cars_search():
    body = call("/carsales-com-au/cars/search", make="Ford", model="Mustang")
    assert body["count"] > 100 and len(body["results"]) >= 22 and body["next"]
    first = body["results"][0]
    assert first["make"] == "Ford" and first["model"] == "Mustang" and first["link"]
    page2 = call("/carsales-com-au/cars/search", make="Ford", model="Mustang", page=2)
    assert page2["current_page"] == 2 and page2["results"]
    call("/carsales-com-au/cars/search", status=400, body_type="spaceship")


def test_makes_list():
    body = call("/carsales-com-au/makes/list")
    assert body["count"] > 100 and any(m["name"] == "Ford" for m in body["results"])


def test_models_list():
    body = call("/carsales-com-au/models/list", make="Ford")
    assert body["make"] == "Ford" and any(m["name"] == "Mustang" for m in body["results"])
    call("/carsales-com-au/models/list", status=404, make="Fordd")


def test_cars_filters():
    body = call("/carsales-com-au/cars/filters", filter="body_type")
    assert body["count"] >= 10 and {"suv", "ute", "sedan"} <= {r["value"] for r in body["results"]}
    call("/carsales-com-au/cars/filters", status=400, filter="price")


def test_model_details():
    body = call("/carsales-com-au/models/details", make="Ford", model="Mustang")
    assert (body["make"], body["model"]) == ("Ford", "Mustang") and body["price"]["min"] and body["badges"]
    call("/carsales-com-au/models/details", status=404, make="Ford", model="Nope")
