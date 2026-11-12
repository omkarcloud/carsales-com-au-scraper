"""Reference resolvers, link builders and the filter tables for
/carsales-com-au/*.

ONE param per input: `car` accepts a bare listing id OR any carsales.com.au
listing link. Resolvers raise ValueError with a user-facing message
(RefField turns it into a 400).

Identifier shapes (carsales "network ids"):
  * listing   OAG-AD-26091046   a dealer's car
              SSE-AD-21038700   a private seller's car
              SHRM-AD-686685    a showroom car (a new model to order)
  * seller    AGC-SELLER-18571 (dealer), SSE-SELLER-21038700 (private),
              CSN-SELLER-88 (carsales' own showroom)
  * link      https://www.carsales.com.au/cars/details/<slug>/<id>/
              (the site ignores the slug)
"""
import re
from urllib.parse import quote, urlparse

SITE = "https://www.carsales.com.au"

LISTING_ID_RE = re.compile(r"^[A-Z]{2,6}-AD-[0-9]{3,12}$")
_LINK_ID_RE = re.compile(r"/details/(?:[^/?#]+/)?([A-Za-z]{2,6}-AD-[0-9]{3,12})(?:[/?#]|$)", re.I)
SELLER_ID_RE = re.compile(r"^[A-Z]{2,6}-SELLER-[0-9]+$")


def _host_is_carsales(value):
    host = (urlparse(value).hostname or "").lower()
    return host == "carsales.com.au" or host.endswith(".carsales.com.au")


def resolve_listing(value):
    """Bare listing id or a carsales.com.au listing link -> the id."""
    value = (value or "").strip()
    candidate = value.upper()
    if LISTING_ID_RE.match(candidate):
        return candidate
    low = value.lower()         # a pasted link may be upper-cased ("HTTPS://WWW.CARSALES.COM.AU/...")
    if low.startswith(("http://", "https://", "//", "www.", "carsales.com.au")):
        url = value
        if low.startswith("//"):
            url = "https:" + url
        elif not low.startswith(("http://", "https://")):
            url = "https://" + url
        if not _host_is_carsales(url):
            raise ValueError("Must be a carsales.com.au link.")
        match = _LINK_ID_RE.search(urlparse(url).path)
        if match:
            return match.group(1).upper()
        raise ValueError("Must be a carsales.com.au listing link "
                         "(https://www.carsales.com.au/cars/details/<name>/<id>/).")
    raise ValueError("Must be a listing id (OAG-AD-26091046) or a carsales.com.au listing link.")


def listing_path(listing_id):
    """The path the site serves a listing under for any slug."""
    return f"/cars/details/x/{listing_id}/"


def absolute(link):
    """A site-relative link -> absolute; anything else unchanged."""
    if isinstance(link, str) and link.startswith("/"):
        return SITE + link
    return link or None


def clean_listing_link(link):
    """A card's link without its tracking query (?gts=...&rankingType=...)."""
    if not isinstance(link, str) or not link:
        return None
    return absolute(link.split("?", 1)[0])


# ---- research pages ------------------------------------------------------------------

def slugify(name):
    """A make / model name the way the site's paths spell it: "Mercedes-Benz"
    -> mercedes-benz, "Landcruiser Prado" -> landcruiser-prado, "CX-5" -> cx-5."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug


def research_path(make_slug, model_slug, year=None):
    path = f"/research/{make_slug}/{model_slug}/"
    return path + (f"{year}/" if year else "")


# ---- search filters ------------------------------------------------------------------
# Public value -> the site's own value in the `q` expression. The values are
# the options of each filter on carsales.com.au/cars/ (captured 2026-11-12
# through cars/filters; the site matches them case-insensitively and an
# unknown value is simply a search with 0 results).

STATES = {
    "act": "Australian Capital Territory",
    "nsw": "New South Wales",
    "nt": "Northern Territory",
    "qld": "Queensland",
    "sa": "South Australia",
    "tas": "Tasmania",
    "vic": "Victoria",
    "wa": "Western Australia",
}


# Public value -> the site's value. Literal tables (no helper builds them):
# the listing tooling reads them straight from this file as the params' enums.
CONDITIONS = {"new": "New", "used": "Used"}      # the site's "Used" is "Used, Demo & Near New"
SELLER_TYPES = {"dealer": "Dealer", "private": "Private"}
BODY_TYPES = {
    "bus": "Bus", "cab_chassis": "Cab Chassis", "convertible": "Convertible", "coupe": "Coupe",
    "hatch": "Hatch", "light_truck": "Light Truck", "people_mover": "People Mover", "sedan": "Sedan",
    "suv": "SUV", "ute": "Ute", "van": "Van", "wagon": "Wagon",
}
FUEL_TYPES = {
    "petrol": "Petrol", "diesel": "Diesel", "hybrid": "Hybrid", "plug_in_hybrid": "Plug in Hybrid",
    "electric": "Electric", "dual_fuel": "Dual Fuel", "gas_only": "Gas Only",
}
TRANSMISSIONS = {"automatic": "Automatic", "manual": "Manual", "amt": "AMT"}
DRIVE_TYPES = {
    "4x4": "4x4", "4x2": "4x2", "6x2": "6x2", "6x6": "6x6",
    "front_wheel_drive": "Front Wheel Drive", "rear_wheel_drive": "Rear Wheel Drive",
}
COLOURS = {
    "beige": "Beige", "black": "Black", "blue": "Blue", "bronze": "Bronze", "brown": "Brown",
    "burgundy": "Burgundy", "gold": "Gold", "green": "Green", "grey": "Grey", "magenta": "Magenta",
    "maroon": "Maroon", "orange": "Orange", "pink": "Pink", "purple": "Purple", "red": "Red",
    "silver": "Silver", "white": "White", "yellow": "Yellow",
}

# Public sort -> the site's `sort` value (None = the site's default,
# "Featured"). "Recently updated" exists on the site but needs a login.
SORTS = {
    "featured": None,
    "price_low_to_high": "~Price",
    "price_high_to_low": "Price",
    "odometer_low_to_high": "~Odometer",
    "odometer_high_to_low": "Odometer",
    "year_new_to_old": "Year",
    "year_old_to_new": "~Year",
    "power_high_to_low": "Power",
    "acceleration_high_to_low": "Acceleration",
}

# cars/filters: public filter name -> the site's filter id. Each is a search
# param of the same name, so an option's `value` can be passed straight back
# to cars/search.
FILTERS = {
    "body_type": "BodyStyle",
    "fuel_type": "FuelType",
    "transmission": "GenericGearType",
    "drive_type": "Drive",
    "colour": "Colour",
    "condition": "Condition",
    "seller_type": "SellerType",
    "state": "State",
    "cylinders": "Cylinders",
    "doors": "Doors",
}
# The value table behind each filter (None: the value is a number).
FILTER_VALUES = {
    "body_type": BODY_TYPES, "fuel_type": FUEL_TYPES, "transmission": TRANSMISSIONS,
    "drive_type": DRIVE_TYPES, "colour": COLOURS, "condition": CONDITIONS, "seller_type": SELLER_TYPES,
    "state": STATES, "cylinders": None, "doors": None,
}
MAKE_FILTER = "Make"


def public_value(filter_name, site_value):
    """A filter option's site value -> the value cars/search takes for it:
    the table's public key ("Front Wheel Drive" -> front_wheel_drive, "New
    South Wales" -> nsw), a number for cylinders / doors."""
    table = FILTER_VALUES.get(filter_name)
    if table is None:
        digits = re.sub(r"[^0-9]", "", str(site_value or ""))
        return int(digits) if digits else None
    low = str(site_value or "").lower()
    for key, value in table.items():
        if value.lower() == low:
            return key
    return re.sub(r"[^a-z0-9]+", "_", low).strip("_") or None


SEARCH_PATH = "/cars/"


def _term(value):
    """A value inside the expression. The grammar's own separators are the
    dot and the parentheses; a value never needs them escaped on the site
    (its own links carry "Mercedes-Benz", "CX-5", "Landcruiser Prado" as
    they are), so only characters that would break the grammar are dropped."""
    return re.sub(r"[()]", " ", str(value)).strip()


def _range(low, high):
    return f"range({'' if low is None else low}..{'' if high is None else high})"


def search_expression(*, query=None, make=None, model=None, badge=None, condition=None,
                      seller_type=None, state=None, region=None, body_type=None, fuel_type=None,
                      transmission=None, drive_type=None, colour=None, cylinders=None, doors=None,
                      min_price=None, max_price=None, min_year=None, max_year=None,
                      min_odometer=None, max_odometer=None, min_seats=None, max_seats=None, **_):
    """The search filters -> carsales' `q` expression, or None for no filter.

        (And.Make.Toyota._.Model.Corolla._.State.Victoria._.Year.range(2018..2020).)

    Every argument is already the site's own value (the schema maps the
    public choices through the tables above)."""
    terms = []

    def add(name, value):
        if value is not None and value != "":
            terms.append(f"{name}.{_term(value)}.")

    add("Make", make)
    add("Model", model)
    add("Badge", badge)
    add("Condition", condition)
    add("SellerType", seller_type)
    add("State", state)
    add("Region", region)
    add("BodyStyle", body_type)
    add("FuelType", fuel_type)
    add("GenericGearType", transmission)
    add("Drive", drive_type)
    add("Colour", colour)
    add("Cylinders", cylinders)
    add("Doors", doors)
    for name, low, high in (("Price", min_price, max_price), ("Year", min_year, max_year),
                            ("Odometer", min_odometer, max_odometer), ("Seats", min_seats, max_seats)):
        if low is not None or high is not None:
            terms.append(f"{name}.{_range(low, high)}.")
    if query:
        terms.append(f"CarAll.keyword({_term(query)}).")
    if not terms:
        return None
    return "(And." + "_.".join(terms) + ")"


def search_query(expression=None, sort=None):
    """The page query string of a search ("" for the unfiltered default)."""
    parts = []
    if expression:
        parts.append("q=" + quote(expression, safe="()._~"))
    if sort:
        parts.append("sort=" + quote(sort, safe="~"))
    return ("?" + "&".join(parts)) if parts else ""
