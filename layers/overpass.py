import requests

_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

def overpass_post(query, timeout=60):
    """POST a query to Overpass, falling back to mirror on 429/5xx/406."""
    last_exc = None
    for url in _MIRRORS:
        try:
            r = requests.post(url, data={"data": query}, timeout=timeout)
            if r.status_code in (406, 429) or r.status_code >= 500:
                last_exc = requests.HTTPError(f"{r.status_code} from {url}", response=r)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_exc = e
            continue
    raise last_exc
