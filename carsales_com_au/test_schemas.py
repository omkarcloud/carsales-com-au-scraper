"""Offline tests for the /carsales-com-au/* request schemas.

    python -m pytest carsales_com_au/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carsales_com_au import refs, schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402


def _errors(schema, params):
    with pytest.raises(ValidationError) as e:
        schema().load(params)
    return e.value.normalized_messages()


# ---- cars/details --------------------------------------------------------------------

def test_car_schema_accepts_id_and_link():
    assert schemas.CarSchema().load({"car": "oag-ad-26091046"}) == {"car": "OAG-AD-26091046"}
    link = "https://www.carsales.com.au/cars/details/2020-toyota-corolla-sx-hybrid-auto/OAG-AD-26091046/?gts=1"
    assert schemas.CarSchema().load({"car": link}) == {"car": "OAG-AD-26091046"}
    assert schemas.CarSchema().load({"car": " SHRM-AD-686685 "}) == {"car": "SHRM-AD-686685"}


@pytest.mark.parametrize("value, message", [
    ("", "Must not be empty."),
    ("26091046", "Must be a listing id (OAG-AD-26091046) or a carsales.com.au listing link."),
    ("https://example.com/cars/details/x/OAG-AD-26091046/", "Must be a carsales.com.au link."),
    ("https://www.carsales.com.au/cars/toyota/",
     "Must be a carsales.com.au listing link (https://www.carsales.com.au/cars/details/<name>/<id>/)."),
])
def test_car_schema_rejects(value, message):
    assert _errors(schemas.CarSchema, {"car": value}) == {"car": [message]}


def test_car_schema_requires_car_and_rejects_siblings():
    assert _errors(schemas.CarSchema, {}) == {"car": ["Missing data for required field."]}
    errors = _errors(schemas.CarSchema, {"car": "OAG-AD-26091046", "url": "https://www.carsales.com.au/"})
    assert errors == {"url": ["Unknown field."]}
    assert "id" in _errors(schemas.CarSchema, {"car": "OAG-AD-26091046", "id": "OAG-AD-26091046"})


# ---- cars/search ---------------------------------------------------------------------

def test_search_schema_defaults():
    loaded = schemas.CarsSearchSchema().load({})
    assert loaded["page"] == 1 and loaded["sort"] is None
    assert all(value is None for name, value in loaded.items() if name != "page")
    assert set(loaded) == {
        "query", "make", "model", "badge", "condition", "seller_type", "state", "region", "body_type",
        "fuel_type", "transmission", "drive_type", "colour", "cylinders", "doors", "min_price", "max_price",
        "min_year", "max_year", "min_odometer", "max_odometer", "min_seats", "max_seats", "sort", "page"}


def test_search_schema_maps_choices_to_site_values():
    loaded = schemas.CarsSearchSchema().load({
        "make": " Toyota ", "model": "Landcruiser  Prado", "condition": "USED", "seller_type": "dealer",
        "state": "NSW", "region": "Sydney", "body_type": "suv", "fuel_type": "plug_in_hybrid",
        "transmission": "automatic", "drive_type": "front_wheel_drive", "colour": "White",
        "cylinders": "4", "doors": "5", "min_price": "10000", "max_price": "40000", "min_year": "2018",
        "max_odometer": "80000", "min_seats": "5", "sort": "price_low_to_high", "page": "3", "query": "sunroof"})
    assert loaded["make"] == "Toyota" and loaded["model"] == "Landcruiser Prado"
    assert loaded["condition"] == "Used" and loaded["seller_type"] == "Dealer"
    assert loaded["state"] == "New South Wales" and loaded["body_type"] == "SUV"
    assert loaded["fuel_type"] == "Plug in Hybrid" and loaded["drive_type"] == "Front Wheel Drive"
    assert loaded["colour"] == "White" and loaded["transmission"] == "Automatic"
    assert (loaded["cylinders"], loaded["doors"], loaded["min_price"], loaded["page"]) == (4, 5, 10000, 3)
    assert loaded["sort"] == "~Price"
    # and the loaded values are exactly what the search expression takes
    assert refs.search_expression(**loaded).startswith(
        "(And.Make.Toyota._.Model.Landcruiser Prado._.Condition.Used._.SellerType.Dealer"
        "._.State.New South Wales._.Region.Sydney._.BodyStyle.SUV._.FuelType.Plug in Hybrid")


@pytest.mark.parametrize("sort", list(refs.SORTS))
def test_search_schema_sorts(sort):
    assert schemas.CarsSearchSchema().load({"sort": sort})["sort"] == refs.SORTS[sort]


@pytest.mark.parametrize("params, field, fragment", [
    ({"body_type": "spaceship"}, "body_type", "Must be one of: bus, cab_chassis"),
    ({"state": "new south wales"}, "state", "Must be one of: act, nsw"),
    ({"sort": "newest"}, "sort", "Must be one of: featured, price_low_to_high"),
    ({"condition": "demo"}, "condition", "Must be one of: new, used."),
    ({"page": "0"}, "page", "Must be greater than or equal to 1 and less than or equal to 20."),
    ({"page": "21"}, "page", "Must be greater than or equal to 1 and less than or equal to 20."),
    ({"page": "two"}, "page", "Not a valid integer."),
    ({"min_price": "-1"}, "min_price", "Must be greater than or equal to 0."),
    ({"cylinders": "0"}, "cylinders", "Must be greater than or equal to 1"),
    ({"make": "x" * 61}, "make", "Longer than maximum length 60."),
    ({"model": "Corolla"}, "model", "model needs a make."),
    ({"make": "Toyota", "badge": "SX"}, "badge", "badge needs a model."),
    ({"region": "Sydney"}, "region", "region needs a state."),
    ({"min_price": "5", "max_price": "4"}, "min_price", "min_price must not be greater than max_price."),
    ({"min_year": "2021", "max_year": "2020"}, "min_year", "min_year must not be greater than max_year."),
    ({"url": "https://www.carsales.com.au/cars/"}, "url", "Unknown field."),
    ({"offset": "22"}, "offset", "Unknown field."),
])
def test_search_schema_rejects(params, field, fragment):
    errors = _errors(schemas.CarsSearchSchema, params)
    assert list(errors) == [field]
    assert fragment in errors[field][0]


def test_search_schema_error_body_names_the_field():
    data, body = load_query(schemas.CarsSearchSchema, {"fuel_type": "coal"})
    assert data is None
    assert body["error"].startswith("Invalid parameters: fuel_type: Must be one of: petrol, diesel")
    assert list(body["errors"]) == ["fuel_type"]


def test_empty_values_mean_not_set():
    loaded = schemas.CarsSearchSchema().load({"make": "  ", "query": "", "state": ""})
    assert loaded["make"] is None and loaded["query"] is None and loaded["state"] is None


# ---- makes/list, models/list ---------------------------------------------------------

def test_makes_schema():
    assert schemas.MakesListSchema().load({}) == {"condition": None}
    assert schemas.MakesListSchema().load({"condition": "new"}) == {"condition": "New"}
    assert _errors(schemas.MakesListSchema, {"make": "Toyota"}) == {"make": ["Unknown field."]}


def test_models_schema():
    assert schemas.ModelsListSchema().load({"make": "toyota"}) == {"make": "toyota", "condition": None}
    assert _errors(schemas.ModelsListSchema, {}) == {"make": ["Missing data for required field."]}
    assert _errors(schemas.ModelsListSchema, {"make": " "}) == {"make": ["Must not be empty."]}


# ---- cars/filters --------------------------------------------------------------------

def test_filters_schema():
    loaded = schemas.CarsFiltersSchema().load({"filter": "Body_Type", "make": "Toyota", "state": "vic"})
    assert loaded["filter"] == "body_type" and loaded["make"] == "Toyota" and loaded["state"] == "Victoria"
    assert "sort" not in loaded and "page" not in loaded
    assert _errors(schemas.CarsFiltersSchema, {}) == {"filter": ["Missing data for required field."]}
    errors = _errors(schemas.CarsFiltersSchema, {"filter": "price"})
    assert errors["filter"][0].startswith("Must be one of: body_type, fuel_type, transmission")
    assert _errors(schemas.CarsFiltersSchema, {"filter": "colour", "page": "2"}) == {"page": ["Unknown field."]}
    assert _errors(schemas.CarsFiltersSchema, {"filter": "colour", "model": "Corolla"}) == \
        {"model": ["model needs a make."]}


@pytest.mark.parametrize("name", list(refs.FILTERS))
def test_filters_schema_accepts_every_filter(name):
    assert schemas.CarsFiltersSchema().load({"filter": name})["filter"] == name


# ---- models/details ------------------------------------------------------------------

def test_model_details_schema():
    assert schemas.ModelDetailsSchema().load({"make": "Toyota", "model": "Corolla"}) == \
        {"make": "Toyota", "model": "Corolla", "year": None}
    assert schemas.ModelDetailsSchema().load({"make": "Mazda", "model": "CX-5", "year": "2020"})["year"] == 2020
    assert _errors(schemas.ModelDetailsSchema, {"make": "Toyota"}) == {"model": ["Missing data for required field."]}
    assert "year" in _errors(schemas.ModelDetailsSchema, {"make": "Toyota", "model": "Corolla", "year": "soon"})
    assert "year" in _errors(schemas.ModelDetailsSchema, {"make": "Toyota", "model": "Corolla", "year": "2101"})


def test_every_field_is_documented():
    for schema in (schemas.CarsSearchSchema, schemas.CarSchema, schemas.MakesListSchema,
                   schemas.ModelsListSchema, schemas.CarsFiltersSchema, schemas.ModelDetailsSchema):
        for name, field in schema().fields.items():
            assert field.metadata.get("description"), f"{schema.__name__}.{name} has no description"
