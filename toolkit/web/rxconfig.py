"""Reflex app configuration."""

import os

from dotenv import load_dotenv

load_dotenv()

import reflex as rx  # noqa: E402

# Determine run mode from environment (matches mcs-agent-analyser pattern)
is_prod = os.getenv("REFLEX_ENV", "dev") == "prod"

if is_prod:
    # api_url is the public URL the BROWSER uses to connect WebSocket.
    # It is baked into the JS bundle by `reflex export` at image build time,
    # so it must be passed as the API_URL build arg to `docker build` /
    # `az acr build`. Defaults to localhost:2009 for local Docker testing
    # (nginx on 2009 proxies /_event/ -> granian on 8000 internally).
    # On ACA, pass the HTTPS FQDN: --build-arg API_URL=https://<fqdn>
    config = rx.Config(
        app_name="web",
        api_url=os.getenv("API_URL", "http://localhost:2009"),
        # Avoid common/default collisions in managed environments.
        frontend_port=int(os.getenv("FRONTEND_PORT", "3100")),
        backend_port=int(os.getenv("BACKEND_PORT", "8000")),
        disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],
    )
else:
    config = rx.Config(
        app_name="web",
        frontend_port=int(os.getenv("FRONTEND_PORT", "3000")),
        backend_port=int(os.getenv("BACKEND_PORT", "8000")),
        disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],
    )
