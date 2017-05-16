#!/usr/bin/env python
"""Move integration details from the Configuration file into the
database as ExternalIntegrations
"""
import os
import sys
import json
import logging
from nose.tools import set_trace

bin_dir = os.path.split(__file__)[0]
package_dir = os.path.join(bin_dir, "..")
sys.path.append(os.path.abspath(package_dir))

from core.model import (
    ExternalIntegration,
    get_one_or_create,
    production_session,
)

from api.config import Configuration
from api.admin.config import Configuration as AdminConfiguration


log = logging.getLogger(name="Circulation manager configuration import")

def log_import(service_name):
    log.info("Importing configuration for %s" % service_name)

try:
    Configuration.load()
    _db = production_session()

    # Import Adobe Vendor ID configuration.
    adobe_conf = Configuration.integration(Configuration.ADOBE_VENDOR_ID_INTEGRATION)
    if adobe_conf:
        log_import(Configuration.ADOBE_VENDOR_ID_INTEGRATION)
        adobe, ignore = get_one_or_create(
            _db, ExternalIntegration, provider=ExternalIntegration.ADOBE_VENDOR_ID
        )

        adobe.username = adobe_conf.get(Configuration.ADOBE_VENDOR_ID)
        node_value = adobe_conf.get(Configuration.ADOBE_VENDOR_ID_NODE_VALUE)
        if node_value:
            adobe.set_setting(u"node_value", node_value)

    # Import Google OAuth configuration.
    google_oauth_conf = AdminConfiguration.integration(AdminConfiguration.GOOGLE_OAUTH_INTEGRATION)
    if google_oauth_conf:
        log_import(AdminConfiguration.GOOGLE_OAUTH_INTEGRATION)
        admin_auth_service, ignore = get_one_or_create(
            _db, ExternalIntegration, provider=ExternalIntegration.GOOGLE_OAUTH
        )

        admin_auth_service.url = google_oauth_conf.get("web", {}).get("auth_uri")
        admin_auth_service.username = google_oauth_conf.get("web", {}).get("client_id")
        admin_auth_service.password = google_oauth_conf.get("web", {}).get("client_secret")

        auth_domain = Configuration.policy(AdminConfiguration.ADMIN_AUTH_DOMAIN)
        admin_auth_service.type = ExternalIntegration.ADMIN_AUTH_TYPE
        if auth_domain:
            admin_auth_service.set_setting("domains", json.dumps([auth_domain]))

    # Import Patron Web Client configuration.
    patron_web_client_conf = Configuration.integration(Configuration.PATRON_WEB_CLIENT_INTEGRATION)
    if patron_web_client_conf:
        log_import(Configuration.PATRON_WEB_CLIENT_INTEGRATION)
        service, ignore = get_one_or_create(
            _db, ExternalIntegration, provider=ExternalIntegration.PATRON_WEB_CLIENT
        )

        service.url = patron_web_client_conf.get(Configuration.URL)

    # Import Staff Picks configuration.
    staff_picks_conf = Configuration.integration(Configuration.STAFF_PICKS_INTEGRATION)
    if staff_picks_conf:
        log_import(Configuration.STAFF_PICKS_INTEGRATION)
        service, ignore = get_one_or_create(
            _db, ExternalIntegration, provider=ExternalIntegration.STAFF_PICKS
        )
        service.url = staff_picks_conf.get(Configuration.URL)
        del staff_picks_conf[Configuration.URL]
        [service.set_setting(k, v) for k, v in staff_picks_conf.items()]
finally:
    _db.commit()
    _db.close()