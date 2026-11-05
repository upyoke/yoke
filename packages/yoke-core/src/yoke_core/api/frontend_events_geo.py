"""Optional DB-IP enrichment from the proxy-validated request client."""

import os

import maxminddb

from yoke_core.frontend_events.events_device import device_props as device_props

GEO_FIELDS = {"client_ip", "geo_country", "geo_region", "geo_city", "network_org"}


def _lookup(setting, address):
    filename = os.environ.get(setting)
    if not filename:
        return {}
    try:
        with maxminddb.open_database(filename) as reader:
            record = reader.get(address)
        return record if isinstance(record, dict) else {}
    except Exception:
        # Optional enrichment never interrupts admission and never logs addresses.
        return {}


def geo_props(client):
    """Keep the trusted address even when optional databases are unavailable."""
    if client is None or not client.host:
        return {}
    address = client.host
    city = _lookup("YOKE_GEOIP_CITY_DB", address)
    asn = _lookup("YOKE_GEOIP_ASN_DB", address)
    regions = city.get("subdivisions") or [{}]
    props = {
        "client_ip": address,
        "geo_country": (city.get("country") or {}).get("iso_code"),
        "geo_region": (regions[0].get("names") or {}).get("en"),
        "geo_city": ((city.get("city") or {}).get("names") or {}).get("en"),
        "network_org": asn.get("autonomous_system_organization"),
    }
    return {key: value for key, value in props.items() if value}
