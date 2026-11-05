"""Explicit DB seeding for protocol fixtures; never installed with the product."""

from openasrportal.api.server import Portal as Application


def portal_for_tests(store, api_key, admin_alias, **kwargs):
    password = admin_alias if len(admin_alias) >= 12 else admin_alias + "-password"
    if api_key:
        store.bootstrap_key(api_key)
    if not store.auth.initialized():
        store.auth.setup(password)
    portal = Application(store, **kwargs)
    portal.test_admin_alias = admin_alias
    portal.test_admin_password = password
    portal.test_admin_token = store.auth.issue_session()["token"]
    return portal


def fixture_token(portal, key):
    return portal.test_admin_token if key == portal.test_admin_alias else key
