"""carsales.com.au answers -> clean dicts. Pure functions, no I/O.

The site's front end is a server-driven UI: every JSON call answers a tree
of typed components ({"type": "ListingCard", ...}, {"type": "Text",
"value": ...}) plus a flat `metaData` list. Nothing here depends on where a
component sits in the layout: components are found by type or by their
`id`, and labelled values by the label next to them.

Fixtures (carsales_com_au/fixtures/, captured 2026-11-12 through the
gateway exit with the transport's own headers):

  search_corolla_page1.json        POST /_api/search-core/cars/?q=(And.Make.Toyota._.Model.Corolla.)
                                   featured sort: 22 organic + 8 promoted cards
  search_corolla_price_page2.json  the pagination postback of the same search sorted by price
  search_small_last_page.json      the last page (2 of 2) of a small search
  search_no_results.json           a search with 0 results
  facet_makes.json                 the Make filter's options (popular + all)
  facet_models_toyota.json         the Model options under Toyota
  facet_body_type.json             the Body type filter's options
  facet_state.json                 the State filter's options
  details_dealer_used.json         POST /_api/details-core/... a dealer's used car
  details_private.json             a private seller's car (phone behind login)
  details_showroom.json            a showroom car (new model to order)
  details_dealer_new.json          a branded dealer's new car: dealer name, address, website, no price
  details_not_found.json           the "page not found" tree an unknown id answers with HTTP 404
  card_new_no_price.json           one ListingCard of that dealer ("Enquire for price")
  gallery_dealer_used.json         GET /_api/gallery-core/<id>/ of the dealer's car (26 photos)
  price_guide_dealer.html          the price sheets of the three listings
  price_guide_private.html
  price_guide_showroom.html
  research_corolla_2020.json       GET /_api/taco-makemodel/research/toyota/corolla/2020/
  research_corolla_latest.json     the same without a year (the current model year)
  blocked.html                     DataDome's interstitial (fetch.looks_blocked)
"""
import html as html_lib
import json
import re
from urllib.parse import parse_qs, urlsplit

from carsales_com_au.refs import LISTING_ID_RE, SITE, absolute, clean_listing_link

CURRENCY = "AUD"
PAGE_SIZE = 22        # organic cards per page
MAX_PAGES = 20        # the site serves no page after this one, whatever the total

_SKIP_KEYS = frozenset(("tracking", "viewTracking", "hoverTracking"))
_MONTH_NAMES = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), 1)}


# ---- the component tree --------------------------------------------------------------

def walk(node, tooltips=True):
    """Every component (dict) under `node`, in document order. Tracking
    payloads are never entered; `tooltips=False` also skips the body of
    every Tooltip (explanatory copy that is not the value itself)."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in _SKIP_KEYS or not isinstance(value, (dict, list)):
                continue
            if not tooltips and key == "content" and node.get("type") == "Tooltip":
                continue
            yield from walk(value, tooltips)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                yield from walk(item, tooltips)


def find(node, kind, tooltips=True):
    return [n for n in walk(node, tooltips) if n.get("type") == kind]


def first(node, kind):
    for n in walk(node):
        if n.get("type") == kind:
            return n
    return None


def by_id(node, ident):
    """The first component whose `id` or `partialId` is `ident`."""
    for n in walk(node):
        if n.get("id") == ident or n.get("partialId") == ident:
            return n
    return None


def texts(node, tooltips=False):
    """The visible strings under `node` (Text and Link values), in order,
    blanks dropped."""
    out = []
    for n in walk(node, tooltips):
        if n.get("type") in ("Text", "Link"):
            value = n.get("value")
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out


def key_values(payload):
    """metaData's KeyValue entries as one dict (the first value of a key wins;
    the site repeats some)."""
    out = {}
    for entry in (payload or {}).get("metaData") or []:
        if isinstance(entry, dict) and entry.get("type") == "KeyValueMetaData":
            out.setdefault(entry.get("key"), entry.get("value"))
    return out


def group_tokens(payload):
    """The two tokens that carry the page's own state into a form postback."""
    out = {"group": None, "shared_group": None}
    for entry in (payload or {}).get("metaData") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "GroupPostBackMetaData":
            out["group"] = entry.get("postBack")
        elif entry.get("type") == "SharedGroupPostBackMetaData":
            out["shared_group"] = entry.get("postBack")
    return out


def _body(payload):
    """What a call answers apart from the site navigation: the page (`root`)
    and / or the re-rendered parts (`partials`)."""
    payload = payload or {}
    return {"root": payload.get("root"), "partials": {
        key: value for key, value in (payload.get("partials") or {}).items()
        if "navigation" not in key}}


# ---- values --------------------------------------------------------------------------

def clean(value):
    """A trimmed string, or None for empty / placeholder values."""
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def to_int(value):
    """"54,196km" / "1,967" -> int; None when there is no digit."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    digits = re.sub(r"[^\d]", "", str(value or "").split(".")[0])
    return int(digits) if digits else None


def to_number(value):
    """"7.4 L/100km" / "A$1,092.00" -> 7.4 / 1092 (int when whole)."""
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    return int(number) if number.is_integer() else number


def money(value):
    """The first dollar amount in a string ("$25,850 Excl. Est. Govt.
    Charges" -> 25850), None when it carries none."""
    match = re.search(r"\$\s*(\d[\d,]*(?:\.\d+)?)", str(value or ""))
    return to_number(match.group(1)) if match else None


def money_range(value):
    """"$16,700 - $30,400" -> (16700, 30400); a single amount -> (n, n)."""
    amounts = [to_number(m) for m in re.findall(r"\$\s*(\d[\d,]*(?:\.\d+)?)", str(value or ""))]
    if not amounts:
        return None, None
    return amounts[0], amounts[-1]


def slug(value):
    """A label as a snake_case token: "Front Wheel Drive" -> front_wheel_drive."""
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or None


def _month_number(word):
    """A month's name or abbreviation ("March", "Mar", "Sept") -> 1..12; None
    for any other word, also one that merely starts like a month ("Marked")."""
    low = word.lower()
    return next((number for name, number in _MONTH_NAMES.items() if name.startswith(low)), None)


def month_date(value):
    """"April 2020" / "4 months/March 2027" -> "2020-04" / "2027-03";
    "22 Oct 2020" -> "2020-10-22"; a bare year -> "2020". None for anything
    else ("Check with seller")."""
    value = clean(value)
    if not value:
        return None
    # every "<word> <year>" is tried, not only the first: a word that is no
    # month ("until 2026, renewed March 2027") must not hide the date after it
    for match in re.finditer(r"(?:(\d{1,2})\s+)?([A-Za-z]{3,9})\.?\s+(\d{4})", value):
        month = _month_number(match.group(2))
        if month:
            day = match.group(1)
            return f"{match.group(3)}-{month:02d}" + (f"-{int(day):02d}" if day else "")
    match = re.fullmatch(r"(\d{4})", value)
    return match.group(1) if match else None


def image_link(link):
    """A photo link without the site's resize parameters (pxc_method /
    pxc_size): the original, as the page's own schema.org block links it."""
    if not isinstance(link, str) or not link.startswith("http"):
        return None
    if urlsplit(link).path.rsplit("/", 1)[-1].lower().startswith("no-image"):
        return None         # the placeholder the site shows for a car without photos is not a photo
    if "pxc_" in link:
        return link.split("?", 1)[0]
    return link


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ---- price ---------------------------------------------------------------------------

_PRICE_TYPES = {"dap": "drive_away", "egc": "excluding_government_charges",
                "indicativedap": "indicative_drive_away", "indicativeegc": "indicative_excluding_government_charges"}


_PRICE_BASES = frozenset(("drive_away", "excluding_government_charges", "indicative_drive_away",
                          "indicative_excluding_government_charges"))


def price_type(label):
    """The site's price basis label -> a stable token."""
    low = (label or "").lower()
    if not low:
        return None
    indicative = "indicative_" if "indicative" in low else ""
    if "drive away" in low:
        return indicative + "drive_away"
    if "excl" in low or "egc" in low:
        return indicative + "excluding_government_charges"
    return slug(label)


def price_rating(label):
    """carsales' price badge ("FAIR PRICE" / "GOOD PRICE" / "GREAT PRICE") -> fair / good / great."""
    low = (label or "").lower()
    return low.replace("price", "").strip() or None if low.endswith("price") else None


def _price(amount_text, info_texts, rating_label, fallback_amount=None, fallback_type=None):
    amount = money(amount_text)
    if amount is None:
        # the site's own field says 0 for a car without a published price
        amount = (to_number(fallback_amount) or None) if fallback_amount not in (None, "") else None
    # the line under the price is its basis ("Drive away"), or a call to action ("Find out more")
    label = next((t for t in info_texts if "$" not in t and price_type(t) in _PRICE_BASES), None)
    before_charges = next((money(t) for t in info_texts if "$" in t and "excl" in t.lower()), None)
    kind = (price_type(label) or _PRICE_TYPES.get((fallback_type or "").lower())) if amount is not None else None
    if before_charges is None and kind == "excluding_government_charges":
        before_charges = amount
    return {
        "amount": amount,
        "currency": CURRENCY,
        "type": kind,
        "label": label,
        # a listing without a number carries the seller's wording here ("Contact seller")
        "text": clean(amount_text) if amount is None else None,
        "amount_excluding_government_charges": before_charges,
        "rating": price_rating(rating_label),
    }


def _badge_labels(node):
    return [clean(b.get("label")) for b in find(node, "Badge") if clean(b.get("label"))]


# ---- search --------------------------------------------------------------------------

def _tracking(action):
    """A card's own record as the site reports it to its analytics: the only
    place the card carries make / model / year / seller id as fields."""
    providers = ((action or {}).get("tracking") or {}).get("providers") or {}
    return (providers.get("csnInsights") or {}).get("metaData") or {}


def _listing_id(link, fallback=None):
    for part in reversed(urlsplit(link or "").path.strip("/").split("/")):
        if LISTING_ID_RE.match(part.upper()):
            return part.upper()
    fallback = (fallback or "").upper()
    return fallback if LISTING_ID_RE.match(fallback) else None


_STATE_CODES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")


def _seller_line(line):
    """The line under a listing's title -> (listing type, dealer name, state):
    "Dealer used • VIC" -> ("Dealer used", None, "VIC"); a dealer that shows
    its name writes "Dealer new • City Mazda • SA"; the listing page puts the
    state first ("VIC • Dealer used"); "New car to order" has neither."""
    parts = [clean(p) for p in (line or "").split("•") if clean(p)]
    if not parts:
        return None, None, None
    state = next((p for p in parts if p.upper() in _STATE_CODES), None)
    rest = [p for p in parts if p is not state]
    return (rest[0] if rest else None), (rest[1] if len(rest) > 1 else None), state


def _media_counts(badge):
    badge = badge or {}

    def count(key):
        return to_int((badge.get(key) or {}).get("count")) or 0
    return {"image_count": count("images"), "video_count": count("videos"),
            "three_sixty_count": count("threeSixties")}


def parse_card(card):
    """One ListingCard -> a search result."""
    action = card.get("action") or {}
    data = action.get("data") or {}
    track = _tracking(action)
    raw_link = data.get("url") or ""
    title_parts = texts(card.get("title"))
    key_details = {i.get("source"): clean(i.get("title")) for i in find(card.get("keyDetails"), "Icon")}
    listing_type, dealer_name, state = _seller_line(next((t for t in texts(card.get("sellerTitle")) if t), None))
    price_badge = _badge_labels(card.get("priceBadge"))
    badges = _unique(_badge_labels(card.get("badge")) + [
        b for b in _badge_labels(card.get("detailsBadges")) if not price_rating(b)])
    ranking = (parse_qs(urlsplit(raw_link).query).get("rankingType") or [None])[0]
    result_type = clean(track.get("result_type"))
    media = _media_counts(card.get("galleryBadge"))
    images = _unique(image_link(i.get("url")) for i in find(card.get("gallery"), "Image"))
    return {
        "id": _listing_id(raw_link, track.get("networkId")),
        "link": clean_listing_link(raw_link),
        "title": clean(data.get("prefetchTitle")) or clean(" ".join(title_parts)),
        "year": to_int(track.get("year")),
        "make": clean(track.get("make")),
        "model": clean(track.get("model")),
        "variant": title_parts[1] if len(title_parts) > 1 else None,
        "condition": slug(track.get("type")),
        "listing_type": listing_type or clean(track.get("adtype")),
        "odometer_km": to_int(key_details.get("kms-taco")),
        "body_type": key_details.get("body-type"),
        "transmission": key_details.get("transmission"),
        "engine": key_details.get("engine"),
        "build_date": month_date(key_details.get("calendar")),      # "Built: September 2026" on a new car
        "price": _price(next(iter(texts(card.get("price"))), None), texts(card.get("priceInfo")),
                        next(iter(price_badge), None), fallback_amount=track.get("price")),
        "seller": {
            "id": clean(track.get("sellerId")),
            "type": slug(data.get("prefetchSellerType")) or slug((listing_type or "").split(" ")[0]),
            "name": dealer_name,        # only dealers that brand their listings show one
            "is_id_verified": any(b.lower() == "id verified" for b in badges),
        },
        "location": {"state": state or clean(track.get("state")) or clean(data.get("prefetchLocation"))},
        "badges": badges,
        "is_promoted": bool(ranking) or (result_type not in (None, "organic")),
        "promotion_type": ranking,
        **media,
        "images": images,
    }


def _is_suggested(card):
    """The site pads a thin search with "suggested" cars that do not match
    the filters; they are not results."""
    return str(_tracking(card.get("action")).get("suggestedresult")).lower() == "true"


def _cursor(payload, body):
    """What the Next button submits, or None on the last page."""
    form = by_id(body, "pagination-form")
    nav = first(form, "PaginationNav") if form else None
    data = (((nav or {}).get("nextButton") or {}).get("action") or {}).get("data") or {}
    if not form or not data.get("postBack") or (nav or {}).get("currentPage") == "last":
        return None
    return {"url": form.get("postBackUrl"), "form": form.get("id"), "id": data.get("id"),
            "token": data.get("postBack"), **group_tokens(payload)}


def _filter_tokens(payload, body):
    """What each filter of the search form submits to list its options:
    {site filter id: {form, id, url, token}} plus the tokens shared by all."""
    filters = {}
    form_tokens = {}
    for node in find(body, "DrillDown"):
        ident = node.get("id") or ""
        data = (node.get("action") or {}).get("data") or {}
        if not ident.startswith("root-drill-down-") or not data.get("postBackUrl"):
            continue
        form_id = data.get("formId")
        if form_id and form_id not in form_tokens:
            form = by_id(body, form_id)
            form_tokens[form_id] = (form or {}).get("postBack")
        filters[ident[len("root-drill-down-"):]] = {
            "form": form_id, "id": data.get("id"), "url": data.get("postBackUrl"),
            "token": data.get("postBack"), "form_token": form_tokens.get(form_id)}
    if not filters:
        return None
    return {"filters": filters, **group_tokens(payload)}


def parse_search(payload):
    """A search answer (the first page's `root` or a postback's `partials`)
    -> {page, total_count, site_total_pages, sort, results, cursor,
    filter_tokens}. `cursor` and `filter_tokens` are what api.py needs to ask
    for the next page and for a filter's options; they never reach a caller."""
    body = _body(payload)
    meta = key_values(payload)
    cards = [c for c in find(body, "ListingCard") if not _is_suggested(c)]
    nav = first(body, "PaginationNav") or {}
    match = re.search(r"Page\s+([\d,]+)\s+of\s+([\d,]+)", nav.get("label") or "")
    total = to_int(meta.get("tracking/page/listingresultcount"))
    page = to_int(meta.get("tracking/page/pageNumber")) or (to_int(match.group(1)) if match else 1)
    site_pages = to_int(match.group(2)) if match else None
    # a one-page search still renders a Next button with a token: no page follows the last one
    is_last = not cards or (site_pages is not None and page >= site_pages)
    return {
        "page": page,
        "total_count": total if total is not None else (0 if not cards else None),
        "site_total_pages": site_pages,
        "sort": clean(meta.get("tracking/page/sortby")),
        "results": [parse_card(c) for c in cards],
        "cursor": None if is_last else _cursor(payload, body),
        "filter_tokens": _filter_tokens(payload, body),
    }


# ---- filter options ------------------------------------------------------------------

def parse_facet(payload):
    """A filter's option list (the search form's drill-down answer) ->
    {level, options: [{name, value, count, is_popular, is_selected, drill}]}.
    `value` is the site's own token for the option; `drill` is what the
    option submits to list the level under it (a make's models). An option
    the site lists twice (once under "Popular", once in the full list) comes
    back once, flagged, in the full list's order."""
    popup = (payload.get("partials") or {}).get("search-refinements-popup") or _body(payload)
    container = next((d for d in find(popup, "DrillDown") if d.get("level")), None) or {}
    options = {}
    for node in find(popup, "MultiSelect"):
        ident = node.get("id") or ""
        token = ident[len("multi-select-"):] if ident.startswith("multi-select-") else ident
        value = clean(token.replace("__", " "))
        if not value:
            continue
        if value in options:
            entry = options.pop(value)
            entry["is_popular"] = True
            options[value] = entry
            continue
        drill = ((node.get("drillDownAction") or {}).get("data") or {}) if node.get("canDrillDown") else {}
        options[value] = {
            "name": clean(node.get("label")) or value,
            "value": value,
            "count": to_int(node.get("badge")),
            "is_popular": False,
            "is_selected": bool(node.get("isSelected")),
            "drill": {"id": drill.get("id"), "token": drill.get("postBack")} if drill.get("postBack") else None,
        }
    return {"level": clean(container.get("level")), "options": list(options.values()),
            "tokens": group_tokens(payload)}


# ---- listing details -----------------------------------------------------------------

def grid_pairs(node):
    """The label / value grids of the listing page -> [(label, value
    component)]. Sponsored rows (an ad slot where the value would be) are
    dropped."""
    pairs = []
    for grid in find(node, "Grid"):
        items = [g for g in grid.get("children") or [] if isinstance(g, dict) and g.get("type") == "GridItem"]
        for label_item, value_item in zip(items[0::2], items[1::2]):
            label = next(iter(texts(label_item)), None)
            if not label or first(value_item, "GamAd"):
                continue
            pairs.append((label, value_item))
    return pairs


def _value(component):
    """A grid value as text: its strings joined by newlines, a star rating
    as its number; None for a value the site renders as a picture."""
    rating = first(component, "StarRating")
    if rating:
        return clean(str(rating.get("leadingText") or rating.get("rating") or ""))
    values = texts(component)
    return "\n".join(values) if values else None


def _known(value):
    """Seller-side placeholders ("Check with seller") are not values."""
    value = clean(value)
    return None if not value or value.lower() in ("check with seller", "not available", "n/a", "-") else value


def _sections(tab):
    """An accordion tab -> [{category, items: [{name, values}]}]."""
    out = []
    for item in find(tab, "AccordionItem"):
        rows = []
        for label, component in grid_pairs(item):
            values = texts(component)
            if values:
                rows.append({"name": label, "values": values})
        if rows:
            out.append({"category": clean((item.get("title") or "").rstrip("+ ")), "items": rows})
    return out


def _specifications(tab):
    """The spec sheet -> [{category, items: [{name, value}]}]."""
    out = []
    for section in _sections(tab):
        out.append({"category": section["category"], "items": [
            {"name": row["name"], "value": "\n".join(row["values"])} for row in section["items"]]})
    return out


def _json_ld(meta):
    raw = meta.get("page/schema-jsonld")
    if not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _name(value):
    """A value the site only publishes lower-cased ("north wahroonga") in title case."""
    value = clean(value)
    return value.title() if value else None


def _restore_case(lowered, source):
    """`lowered` as it is spelled inside `source` ("sx hybrid" in "2020
    Toyota Corolla SX Hybrid Auto" -> "SX Hybrid"); title case when absent."""
    lowered = clean(lowered)
    if not lowered:
        return None
    index = (source or "").lower().find(lowered.lower())
    return source[index:index + len(lowered)] if index >= 0 else lowered.title()


def _flag(value):
    low = str(value).lower()
    return True if low == "true" else False if low == "false" else None


_PHONE_RE = re.compile(r"^[+()\d][\d\s()+-]{6,}$")
_OVERVIEW_FIELDS = {
    "vehicle description": "variant_description",
    "powerplant type": "powerplant_type",
    "exterior colour": "exterior_colour",
    "interior colour": "interior_colour",
    "model year": "model_year",
    "roadworthy certificate": "roadworthy_certificate",
    "dealer stock id": "stock_number",
}
# Rows that are read into typed fields below, or that repeat the id.
_OVERVIEW_TYPED = frozenset((
    "body type", "transmission", "engine", "fuel consumption combined", "ancap safety rating",
    "registration plate", "registration expiry", "build date", "compliance date", "carsales network id"))


def _seller(root, partials, meta, badges):
    kind = slug(meta.get("tracking/page/details/sellertype"))
    call = texts(by_id(root, "enquiry-form:section:call") or by_id(partials, "enquiry-form:section:call"))
    phone = next((t for t in call if _PHONE_RE.match(t)), None)
    code = next((to_int(t) for t in call if t.lower().startswith("car code")), None)
    profile_block = by_id(root, "dealer-profile-partial") or partials.get("modal:dealer-profile")
    profile = dict((label.lower(), _value(component)) for label, component in grid_pairs(profile_block))
    # a dealer that brands its listings heads the block with its name, shows
    # its street address and links its website; the others get "About this
    # dealer" and a state
    heading = next(iter(texts(profile_block)), None)
    name = heading if heading and heading.lower() not in ("about this dealer", "about this seller") else None
    place = clean(profile.get("location"))
    address = place if place and re.search(r"\d", place) else None
    website = next((_action_link(link) for link in find(profile_block, "Link")
                    if (link.get("value") or "").lower().startswith("visit")), None)
    modal = texts(partials.get("modal:dealer-profile"))
    services = []
    if "Buy from home services" in modal:
        for item in modal[modal.index("Buy from home services") + 1:]:
            if item.lower().startswith("read more"):
                break
            services.append(item)
    seller_id = clean(meta.get("tracking/page/details/sellerid"))
    return {
        "id": seller_id.upper() if seller_id else None,
        "type": kind,
        # null for a dealer that does not brand its listings and for a
        # private seller; the licence number and ABN are pictures, a private
        # seller's number sits behind a login
        "name": name,
        "phone": phone,
        "phone_car_code": code,
        "address": address,
        "website": website,
        "member_since": to_int(profile.get("member since")),
        "listings_count": to_int(profile.get("current ad listings")),
        "is_id_verified": any(b.lower() == "id verified" for b in badges),
        "buy_from_home_services": services,
    }


def parse_details(payload, listing_id=None):
    """A listing answer -> the full record (photos and the price sheet are
    merged in by api.py from their own calls)."""
    root = payload.get("root") or {}
    partials = payload.get("partials") or {}
    meta = key_values(payload)
    ld = _json_ld(meta)

    def detail(name):
        return clean(meta.get(f"tracking/page/details/{name}"))

    title = clean(meta.get("page/title")) or next(iter(texts(by_id(root, "details:body:title"))), None)
    link = clean(meta.get("page/canonical-url"))
    title_block = texts(by_id(root, "details:body:title"))
    listing_type, _, state = _seller_line(next((t for t in title_block[1:] if "•" in t), None))
    if not listing_type:
        listing_type = next((t for t in title_block[1:2]), None)

    key_details = {}
    for item in find(by_id(root, "details:body:key-details"), "GridItem"):
        pair = texts(item)
        if len(pair) >= 2:
            key_details[pair[0].lower()] = pair[1]

    overview = {label.lower(): _value(component) for label, component in grid_pairs(by_id(root, "Overview"))}
    price_block = by_id(root, "price-with-disclaimer-layout") or by_id(partials, "price-with-disclaimer-layout")
    price_inner = texts(by_id(price_block, "price-inner-layout") or price_block)
    all_badges = _badge_labels(price_block) + _badge_labels(by_id(root, "details:body:title"))
    badges = _unique(b for b in all_badges if not price_rating(b))
    price = _price(next((t for t in price_inner if "$" in t), next(iter(price_inner), None)),
                   [t for t in price_inner[1:]], next((b for b in all_badges if price_rating(b)), None),
                   fallback_amount=detail("price"), fallback_type=detail("pricetype"))

    engine = ld.get("vehicleEngine") if isinstance(ld.get("vehicleEngine"), dict) else {}
    displacement = engine.get("engineDisplacement") if isinstance(engine.get("engineDisplacement"), dict) else {}
    body_line = overview.get("body type") or ""
    make = clean((ld.get("brand") or {}).get("name") if isinstance(ld.get("brand"), dict) else None)
    model = clean(ld.get("model"))
    gallery = first(root, "Gallery") or {}
    other = {slug(label): _known(value) for label, value in overview.items()
             if label not in _OVERVIEW_FIELDS and label not in _OVERVIEW_TYPED and _known(value)}
    record = {
        "id": _listing_id(link, listing_id or detail("networkid")),
        "link": link,
        "title": title,
        "year": to_int(ld.get("vehicleModelDate")) or to_int(detail("year")),
        "make": make or _name(detail("make")),
        "model": model or _name(detail("model")),
        "badge": _restore_case(detail("badge"), title),
        "variant_description": _known(overview.get("vehicle description")) or clean(meta.get("page/description")),
        "condition": slug(detail("new_and_used")),
        "listing_type": listing_type,
        "sale_status": detail("salestatus"),
        "price": price,
        # a showroom car has no odometer (the site's own field says 0 for it)
        "odometer_km": to_int(key_details.get("odometer")) if key_details.get("odometer")
        else (to_int(detail("odometermin")) or None),
        "body_type": clean(ld.get("bodyType")) or key_details.get("body type"),
        "fuel_type": key_details.get("fuel") or clean(ld.get("fuelType")),
        "fuel_grade": clean(ld.get("fuelType")),
        "transmission": key_details.get("transmission") or clean(ld.get("vehicleTransmission")),
        "transmission_description": _known(overview.get("transmission")),
        "drive_type": clean(ld.get("driveWheelConfiguration")),
        "engine": _known(overview.get("engine")),
        "engine_size_cc": to_int(displacement.get("value")),
        "powerplant_type": _known(overview.get("powerplant type")),
        "fuel_consumption_l_per_100km": to_number(overview.get("fuel consumption combined")),
        "doors": to_int(ld.get("numberOfDoors")) or to_int((re.search(r"(\d+)\s+doors?", body_line) or [None, None])[1]),
        "seats": to_int(ld.get("seatingCapacity")) or to_int((re.search(r"(\d+)\s+seats?", body_line) or [None, None])[1]),
        "exterior_colour": _known(overview.get("exterior colour")) or _name(detail("colour")) or key_details.get("colour"),
        "interior_colour": _known(overview.get("interior colour")),
        "ancap_rating": to_int(overview.get("ancap safety rating")),
        "model_year": _known(overview.get("model year")),
        "build_date": month_date(overview.get("build date")),
        "compliance_date": month_date(overview.get("compliance date")),
        "registration": {
            # the plate is a picture on a dealer's listing and "Check with seller" on a private one
            "plate": _known(overview.get("registration plate")),
            "expiry": month_date(overview.get("registration expiry")),
        },
        "roadworthy_certificate": _known(overview.get("roadworthy certificate")),
        "stock_number": _known(overview.get("dealer stock id")),
        "availability": key_details.get("availability"),
        "description": clean_text(next((t.get("value") for t in find(by_id(root, "details:body:comments"), "Text")
                                        if t.get("value") and not (t.get("semantics") or {}).get("role")), None)),
        "location": {
            "suburb": _name(detail("suburb")),
            "region": _name(detail("region")),
            "state": (detail("state") or state or "").upper() or None,
            "postcode": detail("locationpostcode"),
        },
        "seller": _seller(root, partials, meta, badges),
        "badges": badges,
        "is_clearance": _flag(detail("clearance")),
        "is_latest_stock": _flag(detail("lateststock")),
        "other_details": other,
        "features": _sections(by_id(root, "features-tab")),
        "specifications": _specifications(by_id(root, "specs-tab")),
        **_media_counts(gallery.get("adornment")),
        "images": _unique(image_link(i.get("url")) for i in find(gallery, "Image")),
    }
    if not record["image_count"]:
        record["image_count"] = len(record["images"])
    location = record["location"]
    if not location["suburb"] and not location["postcode"] and not location["state"]:
        # a showroom car is not at a place: the lone region the site reports
        # for it is where the request came from
        location["region"] = None
    return record


def clean_text(value):
    """Free text as the seller wrote it: line breaks kept, edges trimmed."""
    if not isinstance(value, str):
        return None
    value = "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").split("\n")).strip()
    if len(value) > 1 and value[0] == value[-1] == '"':
        value = value[1:-1].strip()      # the site's own showroom blurbs come wrapped in quotes
    return value or None


def parse_gallery(payload):
    """The gallery answer -> {images, videos}: every photo at full size, and
    the link of every video the listing carries."""
    body = _body(payload)
    images = _unique(image_link(n.get("url")) for n in find(body, "ZoomableImage"))
    if not images:
        images = _unique(image_link(n.get("url")) for n in find(body, "GalleryItemThumbnail"))
    videos = _unique(
        clean(n.get("url") or n.get("src") or n.get("videoUrl"))
        for n in walk(body) if "video" in str(n.get("type") or "").lower())
    return {"images": images, "videos": videos}


_ENTRY_RE = re.compile(
    r'<div class="entry\s+(\w+)">.*?class="[^"]*description">(.*?)</div>.*?class="[^"]*amount">(.*?)</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_price_guide(page):
    """The price sheet -> [{name, amount, kind, is_estimate,
    is_government_charge}]: the price before charges ("base"), each charge on
    top ("charge") and the drive-away total ("total"). The site marks an
    estimate with * and a compulsory government fee with #."""
    rows = []
    for kind, description, amount in _ENTRY_RE.findall(page or ""):
        marks = "".join(re.findall(r"<sup>(.*?)</sup>", amount))
        name = clean(html_lib.unescape(_TAG_RE.sub("", description)).lstrip("+ "))
        value = money(html_lib.unescape(_TAG_RE.sub("", re.sub(r"<sup>.*?</sup>", "", amount))))
        if not name or value is None:
            continue
        rows.append({
            "name": name,
            "amount": value,
            "kind": {"initial": "base", "add": "charge", "final": "total"}.get(kind, kind),
            "is_estimate": "*" in marks or "estimate" in name.lower(),
            "is_government_charge": "#" in marks,
        })
    return rows


# ---- model research ------------------------------------------------------------------

def _listed(value):
    """"Hatch, Sedan or Wagon" -> ["Hatch", "Sedan", "Wagon"]."""
    parts = re.split(r",|\bor\b", value or "")
    return [p.strip()[:1].upper() + p.strip()[1:] for p in parts if p.strip()]


def _after(items, label, skip=("#", "^")):
    """The first string after `label` in `items` that is not a footnote mark."""
    for index, item in enumerate(items):
        if item.lower() == label.lower():
            for nxt in items[index + 1:]:
                if nxt not in skip:
                    return nxt
            break
    return None


def _action_link(node):
    data = ((node or {}).get("action") or {}).get("data") or {}
    return absolute(clean(data.get("url")))


def _research_price(amounts, label):
    low, high = money_range(amounts)
    kind = price_type(label)
    if kind and "indicative" not in kind:
        kind = "indicative_" + kind
    return {"min": low, "max": high, "currency": CURRENCY, "type": kind} if low is not None else None


def parse_research(payload):
    """The model research page -> the model's price range, body / fuel /
    seat options, highlights, every badge with its popular features, the
    price range of every model year, the FAQ and the lead expert review."""
    root = payload.get("root") or {}
    meta = key_values(payload)
    hero = texts(by_id(root, "taco-hero-card"))
    price_label = next((t for t in hero if t.lower().startswith("indicative")), None)
    price_text = next((t for t in hero if "$" in t), None)
    stock_button = next((b for b in find(by_id(root, "taco-hero-card"), "Button")
                         if "for sale" in (b.get("label") or "").lower()), None)
    stock_label = (stock_button or {}).get("label") or next((t for t in hero if "for sale" in t.lower()), None)

    everything = texts(root)
    highlights, service, warranty = [], None, None
    start = next((i for i, t in enumerate(everything) if t.lower().startswith("highlights of")), None)
    if start is not None:
        for item in everything[start + 1:start + 12]:
            if item in ("#", "^"):
                continue
            if item.lower() in ("service intervals", "warranty from first registration") or len(item) < 25:
                break
            highlights.append(item)
        window = everything[start:start + 20]
        service = _after(window, "Service intervals")
        warranty = _after(window, "Warranty from first registration")

    badges = []
    for card in find(root, "SplitCard"):
        head = texts(card.get("start"))
        if not head:
            continue
        features = texts(card.get("end"))
        if "Popular features" in features:
            features = features[features.index("Popular features") + 1:]
        else:
            features = []
        price_line = next((t for t in head[1:] if "$" in t), None)
        low, high = money_range(price_line)
        summary = next((t for t in head[1:] if re.search(r"\bvariants?\b", t)), None)
        image = next((i.get("url") for i in find(card.get("start"), "Image")), None)
        badges.append({
            "name": head[0],
            "link": _action_link(card),
            "body_type": clean(re.sub(r"\d+\s+variants?", "", summary or "")),
            "variants_count": to_int((re.search(r"(\d+)\s+variants?", summary or "") or [None, None])[1]),
            "price_min": low,
            "price_max": high,
            "currency": CURRENCY,
            "popular_features": features,
            "image": image if image and not image.endswith(".svg") else None,
        })

    canonical = clean(meta.get("CanonicalUrl")) or ""
    match = re.match(r"(https://[^/]+/research/[^/]+/[^/]+/)", canonical)
    model_link = match.group(1) if match else None
    years = []
    for card in find(root, "ArticleCard"):
        head = clean((card.get("head") or {}).get("value")) if isinstance(card.get("head"), dict) else None
        if not head or not re.fullmatch(r"(19|20)\d{2}", head):
            continue
        body = texts(card.get("body"))
        years.append({
            "year": int(head),
            # the card of the year being viewed carries no link of its own
            "link": _action_link(card) or (f"{model_link}{head}/" if model_link else None),
            "price": _research_price(next((t for t in body if "$" in t), None),
                                     next((t for t in body if "$" not in t), None)),
            "image": next((i.get("url") for i in find(card.get("hero"), "Image")), None),
        })

    faqs = []
    for item in find(root, "AccordionItem"):
        question = clean(item.get("title"))
        answer = clean(" ".join(texts(item)))
        if question and question.endswith("?") and answer:
            faqs.append({"question": question, "answer": answer})

    review = None
    reviews = by_id(root, "ReviewsContainer")
    review_button = next((b for b in find(reviews, "Button") if (b.get("label") or "").lower() == "read full review"), None)
    if review_button:
        # the lead card reads: REVIEW (a badge), the title, the score, "/ 100", the author, "•", the date
        lines = [clean(n.get("value") or n.get("label")) for n in walk(reviews, tooltips=False)
                 if n.get("type") in ("Text", "Link", "Badge") and clean(n.get("value") or n.get("label"))]
        index = lines.index("REVIEW") if "REVIEW" in lines else None
        chunk = lines[index + 1:index + 8] if index is not None else []
        score = next((to_int(t) for i, t in enumerate(chunk) if t.isdigit() and chunk[i + 1:i + 2] == ["/ 100"]), None)
        date = next((month_date(t) for t in chunk if re.search(r"\d{4}$", t) and month_date(t)), None)
        named = [t for t in chunk[1:] if not t.isdigit() and t not in ("/ 100", "•", "Pros", "Cons")
                 and not month_date(t)]
        review = {"title": chunk[0] if chunk else None, "link": _action_link(review_button),
                  "score_out_of_100": score, "author": named[0] if named else None, "published_date": date}

    gallery = first(by_id(root, "hero-gallery") or {}, "Gallery") or {}
    images = _unique(i.get("url") for g in find(root, "Gallery") for i in find(g, "Image"))
    low, high = money_range(price_text)
    if low is None:
        low, high = to_number(meta.get("tracking/taco/page/priceMin")), to_number(meta.get("tracking/taco/page/priceMax"))
    return {
        "make": clean(meta.get("tracking/page/make")),
        "model": clean(meta.get("tracking/page/model")),
        "year": to_int(meta.get("tracking/page/year")),
        "link": clean(meta.get("CanonicalUrl")),
        "title": clean(meta.get("Title")),
        "description": clean(meta.get("Description")),
        "image": clean(meta.get("FeaturedImage")),
        "price": {"min": low, "max": high, "currency": CURRENCY,
                  "type": (_research_price(price_text, price_label) or {}).get("type"), "label": price_label},
        "body_types": _listed(_after(hero, "Body type")),
        "fuel_types": _listed(_after(hero, "Fuel type")),
        "seats": {"min": to_int(meta.get("tracking/taco/page/seatsMin")),
                  "max": to_int(meta.get("tracking/taco/page/seatsMax"))},
        "cars_for_sale_count": to_int(stock_label),
        "cars_for_sale_link": _action_link(stock_button),
        "highlights": highlights,
        "service_interval": service,
        "warranty": warranty,
        "badges_count": len(badges),
        "badges": badges,
        "years": years,
        "faqs": faqs,
        "expert_review": review,
        "image_count": to_int(((gallery.get("adornment") or {}).get("images") or {}).get("count")) or len(images),
        "images": images,
    }


__all__ = ["CURRENCY", "MAX_PAGES", "PAGE_SIZE", "SITE", "parse_card", "parse_details", "parse_facet",
           "parse_gallery", "parse_price_guide", "parse_research", "parse_search"]
