"""Configuration for the Carsales Com Au Scraper. Everything can be set with
an environment variable; the defaults work out of the box.

    PORT                    port the API listens on (default 8000)
    CARSALES_COM_AU_PROXY   proxy URL for every request, e.g.
                            http://user:pass@host:port (default: none —
                            direct). carsales.com.au sits behind DataDome.
                            From a home or office connection you need
                            nothing. On a cloud server, set a residential
                            proxy here — Australian works best.
    CARSALES_COM_AU_PRICE_PROXY
                            proxy URL for the price sheet alone (the
                            price.breakdown of cars/details), default:
                            CARSALES_COM_AU_PROXY. carsales sends the
                            breakdown table to Australian home connections;
                            cloud and overseas addresses mostly get the
                            sheet without it. The sheet is ~9 KB, so an
                            Australian residential proxy here costs little.
    CARSALES_COM_AU_FALLBACK_PROXY
                            proxy URL a worker switches to for 10 minutes
                            after carsales blocks it (default: none, retry
                            on the same exit). Lets you run direct or on a
                            cheap exit and pay for a residential proxy only
                            while you are being blocked.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

CARSALES_COM_AU_PROXY = os.environ.get("CARSALES_COM_AU_PROXY") or None

# The exit every carsales session leaves through: your proxy, or direct.
CARSALES_COM_AU_EXIT = os.environ.get("CARSALES_COM_AU_PROXY") or None

# The exit of the price sheet alone: CARSALES_COM_AU_PRICE_PROXY, else the one above.
CARSALES_COM_AU_PRICE_EXIT = os.environ.get("CARSALES_COM_AU_PRICE_PROXY") or CARSALES_COM_AU_EXIT


# The exit a worker rides for CARSALES_COM_AU_BLOCK_HOLD_S after a block.
CARSALES_COM_AU_FALLBACK_EXIT = os.environ.get("CARSALES_COM_AU_FALLBACK_PROXY") or None
CARSALES_COM_AU_BLOCK_HOLD_S = 600
