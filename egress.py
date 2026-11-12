"""The network helpers the carsales_com_au module needs: one curl_cffi
session per thread, sent from your own connection or through your
CARSALES_COM_AU_PROXY. Nothing else lives here."""
from curl_cffi import requests as curl_requests

ACCEPT_LANGUAGE = "en-AU,en;q=0.9"


def exit_proxy(exit=None):
    """The proxy URL a session should use: CARSALES_COM_AU_PROXY when set
    (http://user:pass@host:port), else None (direct)."""
    value = (exit or "").strip()
    return value if "://" in value else None


def exit_session(exit=None, impersonate="chrome", **kw):
    """A new curl_cffi Session with Chrome's TLS fingerprint, proxied when
    `exit` is a proxy URL, direct otherwise."""
    sess = curl_requests.Session(impersonate=impersonate, **kw)
    proxy = exit_proxy(exit)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    sess.headers.update({"accept-language": ACCEPT_LANGUAGE})
    return sess
