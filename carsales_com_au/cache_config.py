"""Cache TTL per /carsales-com-au/* endpoint (cache.py, keyed on the
validated params).

A search page is cached together with what the site needs to serve the
page after it (the Next button's token and the search form's tokens), so
its TTL is also how old a token may be when it is replayed: they were still
honoured 28 minutes after being issued (2026-11-12), and a refused one is
re-fetched from page 1 by api.py.
"""
from datetime import timedelta

# One row per (filters, sort, page): the parsed page + the tokens for the next
# one. Listings come and go through the day, and the tokens age.
SEARCH_CACHE = timedelta(minutes=15)
# A listing's price, status and photos change a few times in its life.
DETAILS_CACHE = timedelta(hours=6)
# Makes / models / filter values with live counts: the counts drift slowly.
FACET_CACHE = timedelta(hours=6)
# Model research pages are editorial data on a model year.
RESEARCH_CACHE = timedelta(hours=24)
