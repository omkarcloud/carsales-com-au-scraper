"""Offline tests for the carsales.com.au parsers, resolvers and the
transport's response classification.

    python -m pytest carsales_com_au/test_parsers.py -q

Fixtures are real www.carsales.com.au answers captured 2026-11-12
(carsales_com_au/fixtures/, listed in parsers.py's docstring).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carsales_com_au import fetch, parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def fixture(name):
    return json.loads(raw(name))


@pytest.fixture(scope="module")
def page1():
    return P.parse_search(fixture("search_corolla_page1.json"))


@pytest.fixture(scope="module")
def dealer():
    return P.parse_details(fixture("details_dealer_used.json"), "OAG-AD-26091046")


@pytest.fixture(scope="module")
def private():
    return P.parse_details(fixture("details_private.json"), "SSE-AD-21038700")


@pytest.fixture(scope="module")
def showroom():
    return P.parse_details(fixture("details_showroom.json"), "SHRM-AD-686685")


# ---- refs ----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("OAG-AD-26091046", "OAG-AD-26091046"),
    ("  sse-ad-21038700 ", "SSE-AD-21038700"),
    ("SHRM-AD-686685", "SHRM-AD-686685"),
    ("https://www.carsales.com.au/cars/details/2020-toyota-corolla-sx-hybrid-auto/OAG-AD-26091046/", "OAG-AD-26091046"),
    ("https://www.carsales.com.au/cars/details/2024-toyota-corolla-ascent-sport-hybrid-auto/OAG-AD-26452144/"
     "?gts=OAG-AD-26452144&gtsSaleId=OAG-AD-26452144&gtsViewType=topspot&rankingType=topspot", "OAG-AD-26452144"),
    ("http://carsales.com.au/cars/details/SSE-AD-21038700", "SSE-AD-21038700"),
    ("www.carsales.com.au/cars/details/x/shrm-ad-686685/", "SHRM-AD-686685"),
    # a link pasted in capitals is still a link
    ("HTTPS://WWW.CARSALES.COM.AU/CARS/DETAILS/X/OAG-AD-26091046/", "OAG-AD-26091046"),
    ("WWW.carsales.com.au/cars/details/x/OAG-AD-26091046/", "OAG-AD-26091046"),
])
def test_resolve_listing(value, expected):
    assert refs.resolve_listing(value) == expected


@pytest.mark.parametrize("value", [
    "", "26091046", "toyota corolla", "AGC-SELLER-18571",
    "https://example.com/cars/details/x/OAG-AD-26091046/",
    "https://www.carsales.com.au/cars/toyota/corolla/",
    "https://www.carsales.com.au.evil.com/cars/details/x/OAG-AD-26091046/",
])
def test_resolve_listing_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_listing(value)


def test_listing_and_research_paths():
    assert refs.listing_path("OAG-AD-26091046") == "/cars/details/x/OAG-AD-26091046/"
    assert refs.research_path("toyota", "corolla") == "/research/toyota/corolla/"
    assert refs.research_path("toyota", "corolla", 2020) == "/research/toyota/corolla/2020/"
    assert refs.slugify("Mercedes-Benz") == "mercedes-benz"
    assert refs.slugify(" Landcruiser Prado ") == "landcruiser-prado"
    assert refs.slugify("CX-5") == "cx-5"


def test_search_expression():
    assert refs.search_expression() is None
    assert refs.search_expression(make="Toyota", model="Corolla") == "(And.Make.Toyota._.Model.Corolla.)"
    expr = refs.search_expression(make="Toyota", state="Victoria", min_year=2018, max_year=2020,
                                  max_odometer=50000, min_price=10000, query="sunroof")
    assert expr == ("(And.Make.Toyota._.State.Victoria._.Price.range(10000..)._.Year.range(2018..2020)"
                    "._.Odometer.range(..50000)._.CarAll.keyword(sunroof).)")
    # a value can never break out of its term
    assert refs.search_expression(make="To(yo)ta") == "(And.Make.To yo ta.)"
    # a dot in a name is written "_." like the site's own links, or the site drops the filter
    assert refs.search_expression(make="Volkswagen", model="ID.4") == "(And.Make.Volkswagen._.Model.ID_.4.)"
    assert refs.search_expression(model="ID. Buzz", badge="1.4 TSI") == "(And.Model.ID_. Buzz._.Badge.1_.4 TSI.)"
    assert refs.search_expression(query="ID.4") == "(And.CarAll.keyword(ID.4).)"


def test_search_query():
    assert refs.search_query() == ""
    assert refs.search_query(None, "~Price") == "?sort=~Price"
    assert refs.search_query("(And.Make.Toyota._.Model.Landcruiser Prado.)", "Year") == \
        "?q=(And.Make.Toyota._.Model.Landcruiser%20Prado.)&sort=Year"


def test_filter_tables():
    assert refs.STATES["nsw"] == "New South Wales" and len(refs.STATES) == 8
    assert refs.FUEL_TYPES["plug_in_hybrid"] == "Plug in Hybrid"
    assert refs.DRIVE_TYPES["front_wheel_drive"] == "Front Wheel Drive"
    assert refs.SORTS["featured"] is None and refs.SORTS["price_low_to_high"] == "~Price"
    assert refs.public_value("state", "New South Wales") == "nsw"
    assert refs.public_value("drive_type", "Front Wheel Drive") == "front_wheel_drive"
    assert refs.public_value("doors", "5") == 5
    assert refs.public_value("body_type", "Some New Shape") == "some_new_shape"
    # every filter cars/filters lists is a param cars/search takes
    from carsales_com_au import schemas
    assert set(refs.FILTERS) <= set(schemas.CarsSearchSchema().fields)


# ---- value helpers -------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("$26,990", 26990), ("$25,850 Excl. Est. Govt. Charges", 25850), ("A$47.50 ", 47.5),
    ("Contact seller", None), ("", None), (None, None),
])
def test_money(value, expected):
    assert P.money(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("April 2020", "2020-04"), ("4 months/March 2027", "2027-03"), ("22 Oct 2020", "2020-10-22"),
    ("Sept 2020", "2020-09"), ("2019", "2019"), ("Check with seller", None), ("", None), (None, None),
    # a word before a year that is no month does not hide the date after it
    ("Until 2026, renewed March 2027", "2027-03"),
    # a word that only starts like a month is not one
    ("Marked 2020", None), ("Approx 2021", None),
])
def test_month_date(value, expected):
    assert P.month_date(value) == expected


def test_small_helpers():
    assert P.to_int("54,196km") == 54196 and P.to_int("n/a") is None and P.to_int(True) is None
    assert P.to_number("7.4 L/100km") == 7.4 and P.to_number("1798cc") == 1798
    assert P.money_range("$16,700 - $30,400") == (16700, 30400)
    assert P.money_range("Price not available") == (None, None)
    assert P.price_type("Drive away") == "drive_away"
    assert P.price_type("Excl. Govt. Charges") == "excluding_government_charges"
    assert P.price_type("Indicative drive away") == "indicative_drive_away"
    assert P.price_type(None) is None
    assert P.price_rating("FAIR PRICE") == "fair" and P.price_rating("ID verified") is None
    assert P.image_link("https://carsales.pxcrush.net/carsales/cars/dealer/a.jpg?pxc_method=fitfill&pxc_size=720,480") \
        == "https://carsales.pxcrush.net/carsales/cars/dealer/a.jpg"
    assert P.image_link("data:image/png;base64,AAAA") is None
    # the site's "no photo" placeholder is not a photo
    assert P.image_link("https://resource.csnstatic.com/retail/globals/images/no-image-light.png") is None


# ---- search --------------------------------------------------------------------------

def test_search_page1(page1):
    assert page1["page"] == 1
    assert page1["total_count"] == 1966
    assert page1["site_total_pages"] == 90
    assert len(page1["results"]) == 28
    promoted = [r for r in page1["results"] if r["is_promoted"]]
    assert len(promoted) == 8 and {r["promotion_type"] for r in promoted} == {"topspot", "showcase"}
    assert all(r["promotion_type"] is None for r in page1["results"] if not r["is_promoted"])
    # every card is complete
    for r in page1["results"]:
        assert refs.LISTING_ID_RE.match(r["id"])
        assert r["link"] == f"https://www.carsales.com.au{r['link'][len('https://www.carsales.com.au'):]}"
        assert r["link"].endswith(f"/{r['id']}/") and "?" not in r["link"]
        assert r["make"] == "Toyota" and r["model"] == "Corolla"
        assert isinstance(r["year"], int) and isinstance(r["price"]["amount"], int)
        assert r["price"]["currency"] == "AUD"
        assert r["price"]["type"] in ("drive_away", "excluding_government_charges")
        assert r["seller"]["type"] in ("dealer", "private")
        assert r["location"]["state"] in ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")
        assert r["images"] and all(i.startswith("https://") and "pxc_" not in i for i in r["images"])
        assert r["image_count"] >= len(r["images"])


def test_search_card_dealer(page1):
    card = page1["results"][0]
    assert card["id"] == "OAG-AD-26452144"
    assert card["link"] == ("https://www.carsales.com.au/cars/details/"
                            "2024-toyota-corolla-ascent-sport-hybrid-auto/OAG-AD-26452144/")
    assert card["title"] == "2024 Toyota Corolla Ascent Sport Hybrid Auto"
    assert card["year"] == 2024 and card["condition"] == "used" and card["listing_type"] == "Dealer used"
    assert card["odometer_km"] == 39104 and card["body_type"] == "Hatch"
    assert card["transmission"] == "Automatic" and card["engine"] == "4cyl 1.8L Hybrid"
    assert card["price"] == {"amount": 30950, "currency": "AUD", "type": "excluding_government_charges",
                             "label": "Excl. Govt. Charges", "text": None,
                             "amount_excluding_government_charges": 30950, "rating": None}
    assert card["seller"] == {"id": "AGC-SELLER-59236", "type": "dealer", "name": None, "is_id_verified": False}
    assert card["build_date"] is None
    assert card["location"] == {"state": "NSW"}
    assert card["is_promoted"] is True and card["promotion_type"] == "topspot"
    assert card["image_count"] == 20 and card["video_count"] == 0


def test_search_card_private_and_drive_away(page1):
    private = page1["results"][-1]
    assert private["id"] == "SSE-AD-21038700" and private["listing_type"] == "Private"
    assert private["seller"] == {"id": "SSE-SELLER-21038700", "type": "private", "name": None,
                                 "is_id_verified": True}
    assert private["badges"] == ["ID verified"]
    assert private["price"]["amount"] == 13200 and private["price"]["rating"] == "fair"
    drive_away = next(r for r in page1["results"] if r["id"] == "OAG-AD-26091046")
    assert drive_away["price"]["type"] == "drive_away" and drive_away["price"]["label"] == "Drive away"
    assert drive_away["price"]["amount"] == 26990
    assert drive_away["price"]["amount_excluding_government_charges"] == 25850


def test_search_tokens(page1):
    cursor = page1["cursor"]
    assert cursor["url"] == "/?event=search-pagination-changed"
    assert cursor["form"] == "pagination-form" and cursor["id"] == "search-pagination"
    assert cursor["token"].startswith("b64:") and cursor["group"].startswith("b64:")
    assert cursor["shared_group"].startswith("b64:")
    tokens = page1["filter_tokens"]
    assert tokens["group"] == cursor["group"]
    for name in ("Make", "BodyStyle", "FuelType", "GenericGearType", "Drive", "Colour", "Condition",
                 "SellerType", "State", "Cylinders", "Doors"):
        item = tokens["filters"][name]
        assert item["form"] == "search-refinements-form" and item["id"] == f"drill-down-{name}"
        assert item["url"] == "/?event=search-refinements-changing&group=refinements"
        assert item["token"].startswith("b64:")
    # every filter cars/filters offers exists on the site's form
    assert set(refs.FILTERS.values()) <= set(tokens["filters"])


def test_search_postback_page():
    page2 = P.parse_search(fixture("search_corolla_price_page2.json"))
    assert page2["page"] == 2 and page2["total_count"] == 1966 and page2["site_total_pages"] == 90
    assert len(page2["results"]) == 22 and not any(r["is_promoted"] for r in page2["results"])
    # the site orders by the price before government charges
    prices = [r["price"]["amount_excluding_government_charges"] or r["price"]["amount"]
              for r in page2["results"]]
    assert prices == sorted(prices)
    assert page2["cursor"]["token"].startswith("b64:")
    assert page2["filter_tokens"] is None      # the form is not re-rendered by a page change


def test_search_last_page_has_no_cursor():
    last = P.parse_search(fixture("search_small_last_page.json"))
    assert last["page"] == 2 and last["site_total_pages"] == 2 and last["total_count"] == 27
    assert len(last["results"]) == 5
    assert last["cursor"] is None


def test_search_no_results():
    empty = P.parse_search(fixture("search_no_results.json"))
    assert empty["results"] == [] and empty["total_count"] == 0
    assert empty["cursor"] is None and empty["page"] == 1


def test_search_drops_suggested_cards():
    payload = fixture("search_corolla_page1.json")
    cards = P.find(P._body(payload), "ListingCard")
    cards[0]["action"]["tracking"]["providers"]["csnInsights"]["metaData"]["suggestedresult"] = "true"
    assert len(P.parse_search(payload)["results"]) == 27


def test_parse_search_survives_garbage():
    for payload in ({}, {"root": None, "metaData": None}, {"partials": {"x": []}, "metaData": [None, 3]}):
        out = P.parse_search(payload)
        assert out["results"] == [] and out["cursor"] is None and out["filter_tokens"] is None
    assert P.parse_card({})["id"] is None and P.parse_card({})["price"]["amount"] is None


# ---- filter options ------------------------------------------------------------------

def test_facet_makes():
    facet = P.parse_facet(fixture("facet_makes.json"))
    assert facet["level"] == "Make"
    names = [o["name"] for o in facet["options"]]
    assert len(names) == 147 and len(set(names)) == 147      # the popular block is folded in
    assert names == sorted(names, key=str.lower)
    popular = [o["name"] for o in facet["options"] if o["is_popular"]]
    assert popular == ["Audi", "BMW", "BYD", "Ford", "Hyundai", "Mazda", "Mercedes-Benz", "Mitsubishi",
                       "Nissan", "Subaru", "Toyota", "Volkswagen"]
    toyota = next(o for o in facet["options"] if o["name"] == "Toyota")
    assert toyota["value"] == "Toyota" and toyota["count"] == 23186
    assert toyota["drill"]["id"] == "drill-down-Toyota" and toyota["drill"]["token"].startswith("b64:")
    assert facet["tokens"]["group"].startswith("b64:")


def test_facet_models():
    facet = P.parse_facet(fixture("facet_models_toyota.json"))
    assert facet["level"] == "Model" and len(facet["options"]) == 81
    corolla = next(o for o in facet["options"] if o["name"] == "Corolla")
    assert corolla["count"] == 1967 and corolla["is_popular"] is True
    assert sum(o["is_popular"] for o in facet["options"]) == 10


def test_facet_body_type_and_state():
    body = P.parse_facet(fixture("facet_body_type.json"))
    assert [o["value"] for o in body["options"]] == [
        "Bus", "Cab Chassis", "Convertible", "Coupe", "Hatch", "Light Truck", "People Mover", "Sedan",
        "SUV", "Ute", "Van", "Wagon"]
    assert all(isinstance(o["count"], int) for o in body["options"])
    assert {refs.public_value("body_type", o["value"]) for o in body["options"]} == set(refs.BODY_TYPES)
    state = P.parse_facet(fixture("facet_state.json"))
    assert [(o["name"], o["value"]) for o in state["options"]][:2] == [
        ("ACT", "Australian Capital Territory"), ("NSW", "New South Wales")]
    assert {refs.public_value("state", o["value"]) for o in state["options"]} == set(refs.STATES)


def test_facet_survives_garbage():
    assert P.parse_facet({})["options"] == []
    assert P.parse_facet({"partials": {"search-refinements-popup": {"type": "MultiSelect"}}})["options"] == []


# ---- listing details -----------------------------------------------------------------

def test_details_dealer(dealer):
    assert dealer["id"] == "OAG-AD-26091046"
    assert dealer["link"] == ("https://www.carsales.com.au/cars/details/"
                              "2020-toyota-corolla-sx-hybrid-auto/OAG-AD-26091046/")
    assert dealer["title"] == "2020 Toyota Corolla SX Hybrid Auto"
    assert (dealer["year"], dealer["make"], dealer["model"], dealer["badge"]) == (2020, "Toyota", "Corolla", "SX Hybrid")
    assert dealer["variant_description"] == "ZWE211R SX Hybrid Hatchback 5dr E-CVT 1sp 1.8i/53kW Hybrid"
    assert dealer["condition"] == "used" and dealer["listing_type"] == "Dealer used"
    assert dealer["sale_status"] == "for sale"
    assert dealer["price"] == {"amount": 26990, "currency": "AUD", "type": "drive_away", "label": "Drive away",
                               "text": None, "amount_excluding_government_charges": 25850, "rating": "fair"}
    assert dealer["odometer_km"] == 54196 and dealer["body_type"] == "Hatch"
    assert dealer["fuel_type"] == "Hybrid" and dealer["fuel_grade"] == "Petrol - Unleaded ULP"
    assert dealer["transmission"] == "Automatic" and dealer["drive_type"] == "FWD"
    assert dealer["engine_size_cc"] == 1798 and dealer["fuel_consumption_l_per_100km"] == 4.2
    assert dealer["doors"] == 5 and dealer["seats"] == 5 and dealer["ancap_rating"] == 5
    assert dealer["exterior_colour"] == "Glacier White" and dealer["interior_colour"] == "Black Fabric"
    assert dealer["build_date"] == "2020-04" and dealer["compliance_date"] == "2020-05"
    # the plate is a picture on the page: null, never the base64 blob
    assert dealer["registration"] == {"plate": None, "expiry": "2026-11"}
    assert dealer["stock_number"] == "U77103"
    assert dealer["location"] == {"suburb": "Elsternwick", "region": "Melbourne", "state": "VIC", "postcode": "3185"}
    assert dealer["description"].startswith("Super low kilometre 2020 Corolla SX Hybrid Hatch")
    assert "\n" in dealer["description"]
    assert dealer["image_count"] == 26 and len(dealer["images"]) == 4      # the gallery call brings the rest


def test_details_dealer_seller(dealer):
    seller = dealer["seller"]
    assert seller["id"] == "AGC-SELLER-18571" and seller["type"] == "dealer"
    # this dealer does not brand its listings: no name, no street address, no website
    assert seller["name"] is None and seller["address"] is None and seller["website"] is None
    assert seller["phone"] == "(03) 7019 7044" and seller["phone_car_code"] == 1533
    assert seller["member_since"] == 2017 and seller["listings_count"] == 62
    assert "Home test drive" in seller["buy_from_home_services"]
    assert not any("read more" in s.lower() for s in seller["buy_from_home_services"])


def test_details_features_and_specifications(dealer):
    categories = [s["category"] for s in dealer["features"]]
    assert categories[:2] == ["Audio, Visual & Communication", "Safety & Security"] and len(categories) == 14
    airbags = next(i for i in dealer["features"][1]["items"] if i["name"] == "Airbags")
    assert airbags["values"][:2] == ["Driver", "Passenger"] and len(airbags["values"]) == 6
    specs = {s["category"]: {i["name"]: i["value"] for i in s["items"]} for s in dealer["specifications"]}
    assert len(specs) == 11 and sum(len(v) for v in specs.values()) == 89
    assert specs["Engine"]["Engine Size (cc)"] == "1798cc"
    assert specs["Fuel"]["Fuel Capacity"] == "43L"
    assert specs["Probationary plate status"]["Victoria"] == "Approved"
    # no sponsored row and no picture leaks into a value
    flat = json.dumps([dealer["features"], dealer["specifications"], dealer["other_details"]])
    assert "data:image" not in flat and "Sponsored" not in flat


def test_details_private(private):
    assert private["id"] == "SSE-AD-21038700" and private["listing_type"] == "Private"
    assert private["badge"] == "Ascent" and private["model_year"] == "MY11"
    assert private["price"]["type"] == "excluding_government_charges" and private["price"]["amount"] == 13200
    assert private["seller"]["type"] == "private" and private["seller"]["is_id_verified"] is True
    # "View number" sits behind a login; "Check with seller" is not a value
    assert private["seller"]["phone"] is None and private["seller"]["phone_car_code"] is None
    assert private["registration"] == {"plate": None, "expiry": "2027-03"}
    assert private["compliance_date"] is None and private["build_date"] == "2011-11"
    assert private["roadworthy_certificate"] == "Provided at pick-up by seller"
    assert private["badges"] == ["ID verified"]
    assert private["location"] == {"suburb": "North Wahroonga", "region": "Sydney East", "state": "NSW",
                                   "postcode": "2076"}
    assert private["features"][0]["category"] == "After market"
    assert private["seller"]["buy_from_home_services"] == []


def test_details_showroom_is_sparse(showroom):
    assert showroom["id"] == "SHRM-AD-686685" and showroom["condition"] == "showroom"
    assert showroom["listing_type"] == "New car to order"
    assert showroom["price"]["type"] == "indicative_drive_away" and showroom["price"]["amount"] == 78112
    assert showroom["price"]["amount_excluding_government_charges"] is None
    assert showroom["odometer_km"] is None and showroom["availability"] == "Varies"
    assert showroom["exterior_colour"] == "Black" and showroom["interior_colour"] is None
    assert showroom["location"] == {"suburb": None, "region": None, "state": None, "postcode": None}
    assert showroom["seller"]["id"] == "CSN-SELLER-88" and showroom["seller"]["phone"] is None
    assert showroom["badges"] == ["Up to 5 year warranty"]
    assert showroom["description"].startswith("This car is small")
    assert not showroom["description"].endswith('"')
    assert showroom["registration"] == {"plate": None, "expiry": None}
    assert showroom["drive_type"] == "4x4" and showroom["engine_size_cc"] == 1618
    assert len(showroom["specifications"]) == 10
    # the page shows a "no image" placeholder: the car has no photo
    assert showroom["images"] == [] and showroom["image_count"] == 0


def test_details_branded_dealer_new_car():
    record = P.parse_details(fixture("details_dealer_new.json"), "OAG-AD-26489455")
    assert record["id"] == "OAG-AD-26489455" and record["condition"] == "new"
    assert record["listing_type"] == "Dealer new car in stock"
    assert record["seller"] == {
        "id": "AGC-SELLER-11249", "type": "dealer", "name": "City Mazda", "phone": "(08) 7078 1002",
        "phone_car_code": 2010, "address": "432-448 Port Rd. Hindmarsh, SA 5007",
        "website": "https://city-mazda.com.au/", "member_since": 2017, "listings_count": 159,
        "is_id_verified": False, "buy_from_home_services": []}
    assert record["location"] == {"suburb": "Hindmarsh", "region": "Adelaide Eastern", "state": "SA",
                                  "postcode": "5007"}
    # "Enquire for price" / "Find out more": no amount, no basis, the wording kept
    assert record["price"] == {"amount": None, "currency": "AUD", "type": None, "label": None,
                               "text": "Enquire for price", "amount_excluding_government_charges": None,
                               "rating": None}
    assert record["build_date"] == "2026-09" and record["badges"] == ["Up to 5 year warranty"]


def test_card_branded_dealer_without_price():
    card = P.parse_card(fixture("card_new_no_price.json"))
    assert card["id"] == "OAG-AD-26489455" and card["condition"] == "new" and card["listing_type"] == "Dealer new"
    assert card["seller"] == {"id": "AGC-SELLER-11249", "type": "dealer", "name": "City Mazda",
                              "is_id_verified": False}
    assert card["location"] == {"state": "SA"}
    assert card["price"]["amount"] is None and card["price"]["text"] == "Enquire for price"
    assert card["price"]["label"] is None and card["price"]["type"] is None
    assert card["build_date"] == "2026-09" and card["odometer_km"] is None


def test_seller_line():
    assert P._seller_line("Dealer used • VIC") == ("Dealer used", None, "VIC")
    assert P._seller_line("VIC • Dealer used") == ("Dealer used", None, "VIC")
    assert P._seller_line("Dealer new • City Mazda • SA") == ("Dealer new", "City Mazda", "SA")
    assert P._seller_line("New car to order") == ("New car to order", None, None)
    assert P._seller_line(None) == (None, None, None)


def test_details_same_keys_for_every_kind(dealer, private, showroom):
    assert list(dealer) == list(private) == list(showroom) == list(P.parse_details(fixture("details_dealer_new.json")))
    for record in (dealer, private, showroom):
        assert list(record["seller"]) == list(dealer["seller"])
        assert list(record["price"]) == list(dealer["price"])
        flat = json.dumps(record)
        assert '": ""' not in flat and '[""' not in flat
        assert "N/A" not in flat and "Check with seller" not in flat


def test_details_not_found_page():
    payload = fixture("details_not_found.json")
    assert fetch.is_listing(payload) is False
    assert fetch.is_listing(fixture("details_dealer_used.json")) is True
    assert fetch.is_listing(fixture("details_showroom.json")) is True
    assert fetch.is_listing({}) is False and fetch.is_listing({"metaData": [None]}) is False
    # the parser itself never crashes on it
    record = P.parse_details(payload)
    assert record["id"] is None and record["title"] is None and record["features"] == []
    assert P.parse_details({})["price"]["amount"] is None


def test_gallery():
    media = P.parse_gallery(fixture("gallery_dealer_used.json"))
    assert len(media["images"]) == 26 and media["videos"] == []
    assert media["images"][0] == "https://carsales.pxcrush.net/carsales/cars/dealer/ebrxe38y02qhrldep1d635w65.jpg"
    assert len(set(media["images"])) == 26
    assert P.parse_gallery({}) == {"images": [], "videos": []}


def test_price_guide_dealer():
    rows = P.parse_price_guide(raw("price_guide_dealer.html"))
    assert rows == [
        {"name": "Estimated Price Excl. Govt. Charges (EGC)", "amount": 25850, "kind": "base",
         "is_estimate": True, "is_government_charge": False},
        {"name": "Stamp Duty", "amount": 1092, "kind": "charge", "is_estimate": False, "is_government_charge": True},
        {"name": "Transfer Fee", "amount": 47.5, "kind": "charge", "is_estimate": False, "is_government_charge": True},
        {"name": "Drive Away Price", "amount": 26990, "kind": "total", "is_estimate": False,
         "is_government_charge": False},
    ]
    # the charges add up to the total, to the dollar
    assert round(sum(r["amount"] for r in rows[:-1])) == rows[-1]["amount"]


def test_price_guide_private_and_showroom():
    private = P.parse_price_guide(raw("price_guide_private.html"))
    assert [r["kind"] for r in private] == ["base", "charge", "charge", "total"]
    assert private[-1] == {"name": "Estimated Drive Away Price (DAP)", "amount": 13638, "kind": "total",
                           "is_estimate": True, "is_government_charge": False}
    showroom = P.parse_price_guide(raw("price_guide_showroom.html"))
    assert [r["name"] for r in showroom][1:3] == ["Dealer Delivery Fee", "Number Plate Fee"]
    assert showroom[1]["is_government_charge"] is False and showroom[2]["is_government_charge"] is True
    assert showroom[3]["amount"] == 4705.02 and showroom[-1]["amount"] == 78112
    assert P.parse_price_guide("") == [] and P.parse_price_guide(None) == []
    assert P.parse_price_guide(raw("blocked.html")) == []


# ---- model research ------------------------------------------------------------------

def test_research_year():
    model = P.parse_research(fixture("research_corolla_2020.json"))
    assert (model["make"], model["model"], model["year"]) == ("Toyota", "Corolla", 2020)
    assert model["link"] == "https://www.carsales.com.au/research/toyota/corolla/2020/"
    assert model["price"] == {"min": 16700, "max": 30400, "currency": "AUD",
                              "type": "indicative_excluding_government_charges",
                              "label": "Indicative price (EGC)"}
    assert model["body_types"] == ["Hatch", "Sedan", "Wagon"] and model["fuel_types"] == ["Hybrid", "Petrol"]
    assert model["seats"] == {"min": 5, "max": 5}
    assert model["cars_for_sale_count"] == 153
    assert model["cars_for_sale_link"] == "https://www.carsales.com.au/cars/2020/toyota/corolla/"
    assert len(model["highlights"]) == 3 and model["highlights"][2] == "The storage space in the rear is 470L."
    assert model["service_interval"] == "15,000km/12 months"
    assert model["warranty"] == "5 years warranty / unlimited km"
    assert model["badges_count"] == 17 == len(model["badges"])
    sport = next(b for b in model["badges"] if b["name"] == "Ascent Sport" and b["body_type"] == "Sedan")
    assert sport["variants_count"] == 4 and (sport["price_min"], sport["price_max"]) == (18100, 22400)
    assert sport["popular_features"][0] == "Boot space: 470 L" and "Show all specs" not in sport["popular_features"]
    assert sport["link"].startswith("https://www.carsales.com.au/research/toyota/corolla/2020/ascent-sport/")
    unpriced = next(b for b in model["badges"] if b["name"] == "Hybrid WxB")
    assert unpriced["price_min"] is None and unpriced["image"] is None and unpriced["popular_features"] == []
    assert len(model["years"]) == 60 and model["years"][0]["year"] == 2026 and model["years"][-1]["year"] == 1967
    assert model["years"][1] == {
        "year": 2025, "link": "https://www.carsales.com.au/research/toyota/corolla/2025/",
        "price": {"min": 30300, "max": 62800, "currency": "AUD", "type": "indicative_excluding_government_charges"},
        "image": model["years"][1]["image"]}
    assert len(model["faqs"]) == 7 and model["faqs"][1] == {
        "question": "How big is the Toyota Corolla 2020 boot space?",
        "answer": "The Toyota Corolla 2020 has a boot capacity of 470 litres."}
    assert model["expert_review"] == {
        "title": "Toyota Corolla SX Hybrid 2020 Review",
        "link": "https://www.carsales.com.au/editorial/details/toyota-corolla-sx-hybrid-2020-review-126930/",
        "score_out_of_100": 78, "author": "Luke Youlden", "published_date": "2020-10-22"}
    assert model["image_count"] == 6 and model["images"]


def test_research_latest_year():
    model = P.parse_research(fixture("research_corolla_latest.json"))
    assert model["year"] == 2026 and model["link"] == "https://www.carsales.com.au/research/toyota/corolla/"
    assert model["price"]["type"] == "indicative_drive_away" and model["price"]["min"] == 35588
    assert model["body_types"] == ["Hatch", "Sedan"] and model["badges_count"] == 6
    # the card of the year on screen has no link of its own on the site
    assert model["years"][0] == {**model["years"][0], "year": 2026,
                                 "link": "https://www.carsales.com.au/research/toyota/corolla/2026/"}
    assert model["expert_review"]["published_date"] == "2026-02-09"


def test_research_survives_garbage():
    model = P.parse_research({})
    assert model["make"] is None and model["badges"] == [] and model["years"] == [] and model["expert_review"] is None
    assert model["price"] == {"min": None, "max": None, "currency": "AUD", "type": None, "label": None}
    # a gallery whose badge carries no image count
    bare = {"root": {"id": "hero-gallery", "child": {"type": "Gallery", "adornment": {"images": None}}}}
    assert P.parse_research(bare)["image_count"] == 0


# ---- the transport's classification --------------------------------------------------

class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def test_block_page_is_blocked_never_parsed():
    page = raw("blocked.html")
    assert fetch.looks_blocked(page)
    with pytest.raises(fetch.CarsalesBlocked):
        fetch._classify(_Resp(403, page), "search")
    with pytest.raises(fetch.CarsalesBlocked):      # DataDome also answers 200 on some paths
        fetch._classify(_Resp(200, page), "search")
    for name in ("search_corolla_page1.json", "details_dealer_used.json", "price_guide_dealer.html",
                 "research_corolla_2020.json", "gallery_dealer_used.json", "details_not_found.json"):
        assert not fetch.looks_blocked(raw(name)), name


def test_classify_statuses():
    assert fetch._classify(_Resp(200, "{}"), "search") == "{}"
    with pytest.raises(fetch.CarsalesNotFound) as e:
        fetch._classify(_Resp(404, "{}"), "listing OAG-AD-1")
    assert str(e.value) == "listing OAG-AD-1 not found"
    with pytest.raises(fetch.CarsalesBadRequest):
        fetch._classify(_Resp(404, "{}"), "search", fetch.CarsalesBadRequest)
    with pytest.raises(fetch.CarsalesBlocked):
        fetch._classify(_Resp(429, ""), "search")
    with pytest.raises(fetch.CarsalesUpstreamError) as e:
        fetch._classify(_Resp(502, ""), "search")
    assert not isinstance(e.value, fetch.CarsalesBlocked)
    with pytest.raises(fetch.CarsalesUpstreamError):
        fetch._json("<html>", "search")
    with pytest.raises(fetch.CarsalesUpstreamError):
        fetch._json("[]", "search")
