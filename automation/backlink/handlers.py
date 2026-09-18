"""
handlers.py — dispatch (site_id -> site module submit).
"""

from automation.backlink.engine import generic_submit

def get_handler(site_id):
    # Always return the generic engine for any site configuration
    return generic_submit

def supported_sites():
    # Since it's config-driven, we just support anything passed in config.
    # Returning a placeholder or parsing config could be an option, 
    # but the generic engine supports dynamic sites.
    return []
