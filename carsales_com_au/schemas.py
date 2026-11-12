"""Marshmallow request schemas for every /carsales-com-au/* route.

ONE param per input (never a sibling `url` / `id` pair):

    car      a listing id (OAG-AD-26091046, SSE-AD-21038700, SHRM-AD-686685)
             OR any carsales.com.au listing link
    make     a make name as carsales spells it ("Toyota", "Mercedes-Benz");
             makes/list returns every one
    model    a model name of that make ("Corolla", "Landcruiser Prado");
             models/list returns every one

The choice params (condition, body_type, fuel_type, ...) take the public
values of carsales_com_au/refs.py; the schema hands api.py the site's own
value for each, so the search expression is built without another lookup.
Names are matched case-insensitively by the site, and a name it does not
know is a search with 0 results, not an error.
"""
from marshmallow import ValidationError, fields, missing, validate, validates_schema

from schema_fields import BaseSchema, ChoiceField, PageField, PositiveInt, QueryField, RefField, StrippedString
from carsales_com_au import refs
from carsales_com_au.parsers import MAX_PAGES

NAME_MAX = 60


class ListingRefField(RefField):
    resolver = staticmethod(refs.resolve_listing)


class OptionalText(StrippedString):
    """An optional string with a length cap. An empty value means "not
    set" (None). The cap is checked here and not by a validator: marshmallow
    runs validators on the None an empty value becomes, and Length(None)
    is a 500."""

    def __init__(self, max_length, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)
        self.max_length = max_length

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is not None and len(value) > self.max_length:
            raise ValidationError(f"Longer than maximum length {self.max_length}.")
        return value


def _name(description):
    return OptionalText(NAME_MAX, metadata={"description": description})


def _amount(description, maximum=None):
    """An optional whole number >= 0 (a price in AUD, kilometres)."""
    return fields.Integer(strict=False, load_default=None, validate=validate.Range(min=0, max=maximum),
                          metadata={"description": description})


def _choice(table, description):
    return ChoiceField(table, metadata={"description": description})


class _SearchFilters(BaseSchema):
    """The filters cars/search and cars/filters share."""
    query = OptionalText(100, metadata={"description": "keyword to look for in the listing (e.g. sunroof)"})
    make = _name("make name, e.g. Toyota (see makes/list)")
    model = _name("model name of that make, e.g. Corolla (see models/list); needs make")
    badge = _name("badge of that model, e.g. SX Hybrid; needs model")
    condition = _choice(refs.CONDITIONS, "new or used (used includes demo and near-new cars)")
    seller_type = _choice(refs.SELLER_TYPES, "dealer or private")
    state = _choice(refs.STATES, "Australian state or territory: act, nsw, nt, qld, sa, tas, vic, wa")
    region = _name("region inside the state as carsales names it, e.g. Sydney; needs state")
    body_type = _choice(refs.BODY_TYPES, "body type, e.g. suv, hatch, ute")
    fuel_type = _choice(refs.FUEL_TYPES, "fuel type, e.g. petrol, diesel, hybrid, electric")
    transmission = _choice(refs.TRANSMISSIONS, "automatic, manual or amt")
    drive_type = _choice(refs.DRIVE_TYPES, "drive type, e.g. 4x4, front_wheel_drive, rear_wheel_drive")
    colour = _choice(refs.COLOURS, "exterior colour, e.g. white, black, silver")
    cylinders = PositiveInt(max_value=16, metadata={"description": "number of engine cylinders"})
    doors = PositiveInt(max_value=6, metadata={"description": "number of doors"})
    min_price = _amount("lowest price in AUD")
    max_price = _amount("highest price in AUD")
    min_year = PositiveInt(max_value=2100, metadata={"description": "earliest model year"})
    max_year = PositiveInt(max_value=2100, metadata={"description": "latest model year"})
    min_odometer = _amount("lowest odometer reading in km")
    max_odometer = _amount("highest odometer reading in km")
    min_seats = PositiveInt(max_value=60, metadata={"description": "fewest seats"})
    max_seats = PositiveInt(max_value=60, metadata={"description": "most seats"})

    @validates_schema
    def _dependent_filters(self, data, **kwargs):
        if data.get("model") and not data.get("make"):
            raise ValidationError("model needs a make.", "model")
        if data.get("badge") and not data.get("model"):
            raise ValidationError("badge needs a model.", "badge")
        if data.get("region") and not data.get("state"):
            raise ValidationError("region needs a state.", "region")
        for name in ("price", "year", "odometer", "seats"):
            low, high = data.get(f"min_{name}"), data.get(f"max_{name}")
            if low is not None and high is not None and low > high:
                raise ValidationError(f"min_{name} must not be greater than max_{name}.", f"min_{name}")


class CarsSearchSchema(_SearchFilters):
    sort = ChoiceField(refs.SORTS, metadata={
        "description": "result order: featured (default), price_low_to_high, price_high_to_low, "
                       "odometer_low_to_high, odometer_high_to_low, year_new_to_old, year_old_to_new, "
                       "power_high_to_low, acceleration_high_to_low"})
    page = PageField(max_page=MAX_PAGES, metadata={
        "description": f"page number, 22 cars each; carsales serves at most {MAX_PAGES} pages per search"})


class CarSchema(BaseSchema):
    car = ListingRefField(metadata={
        "description": "listing id (e.g. OAG-AD-26091046), or a carsales.com.au listing link"})


class MakesListSchema(BaseSchema):
    condition = _choice(refs.CONDITIONS, "count only new or only used cars")


class ModelsListSchema(BaseSchema):
    make = QueryField(max_length=NAME_MAX, metadata={"description": "make name, e.g. Toyota (see makes/list)"})
    condition = _choice(refs.CONDITIONS, "count only new or only used cars")


class CarsFiltersSchema(_SearchFilters):
    filter = ChoiceField(list(refs.FILTERS), required=True, load_default=missing, metadata={
        "description": "the filter to list values for: " + ", ".join(refs.FILTERS)})


class ModelDetailsSchema(BaseSchema):
    make = QueryField(max_length=NAME_MAX, metadata={"description": "make name, e.g. Toyota"})
    model = QueryField(max_length=NAME_MAX, metadata={"description": "model name, e.g. Corolla"})
    year = PositiveInt(max_value=2100, metadata={
        "description": "model year, e.g. 2020 (default: the current model year)"})
