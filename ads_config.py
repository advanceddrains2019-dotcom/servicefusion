#!/usr/bin/env python3
"""Shared configuration and secret loading for the Google Ads scripts.

Keeps account constants and credential loading in one place so the two
entry-point scripts (lsa_scheduler.py, sage_ads_intelligence.py) can't drift
apart, and so the developer token is never hardcoded in source.
"""

import os

CUSTOMER_ID = "5177347535"
MANAGER_ID = "3087463043"

SECRETS_PATH = "/root/.vikky_secrets"

_SECRETS = {}


def load_secrets(path=SECRETS_PATH):
    """Parse a simple key=value file into a dict."""
    secrets = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return secrets


def get_secret(key, default=""):
    """Return a secret from the environment, falling back to the secrets file."""
    if key in os.environ:
        return os.environ[key]
    global _SECRETS
    if not _SECRETS:
        _SECRETS = load_secrets()
    return _SECRETS.get(key, default)


def get_developer_token():
    """Google Ads developer token — loaded from env/secrets, never hardcoded."""
    token = get_secret("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not token:
        raise RuntimeError(
            "GOOGLE_ADS_DEVELOPER_TOKEN not found in environment or "
            f"{SECRETS_PATH}. Add it there (it is no longer stored in source)."
        )
    return token


def build_ads_client_config():
    """Common GoogleAdsClient config dict shared by all Ads scripts."""
    return {
        "developer_token": get_developer_token(),
        "client_id": get_secret("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": get_secret("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": get_secret("GOOGLE_ADS_REFRESH_TOKEN"),
        "login_customer_id": MANAGER_ID,
        "use_proto_plus": True,
    }
