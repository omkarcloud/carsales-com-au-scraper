"""Configuration for the Carsales Com Au Scraper. Everything can be set with
an environment variable; the defaults work out of the box.

    PORT                    port the API listens on (default 8000)
    CARSALES_COM_AU_PROXY   proxy URL for every request, e.g.
                            http://user:pass@host:port (default: none —
                            direct). carsales.com.au sits behind DataDome.
                            From a home or office connection you need
                            nothing. On a cloud server, set a residential
                            proxy here — Australian works best.

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
