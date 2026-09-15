"""
handlers.py — dispatch (site_id -> site module submit).
"""

from automation.backlink.sites import duplichecker, free_backlinks, pingmylinks, pingmyurls, prepostseo

_HANDLERS = {
    "pingmyurls": pingmyurls.submit,
    "pingmylinks": pingmylinks.submit,
    "prepostseo": prepostseo.submit,
    "duplichecker": duplichecker.submit,
    "free_backlinks": free_backlinks.submit,
}


def get_handler(site_id):
    try:
        return _HANDLERS[str(site_id)]
    except KeyError:
        raise ValueError(
            f"No backlink handler for site '{site_id}'. Available: {sorted(_HANDLERS)}"
        )


def supported_sites():
    return sorted(_HANDLERS)
