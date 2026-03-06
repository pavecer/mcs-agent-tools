"""Reflex app configuration."""

import os

from dotenv import load_dotenv

load_dotenv()

import reflex as rx

# Determine run mode from environment (matches mcs-agent-analyser pattern)
is_prod = os.getenv("REFLEX_ENV", "dev") == "prod"

if is_prod:
    port = int(os.getenv("PORT", "2009"))
    config = rx.Config(
        app_name="web",
        frontend_port=port,
        backend_port=port,
        disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],
    )
else:
    config = rx.Config(
        app_name="web",
        frontend_port=int(os.getenv("FRONTEND_PORT", "3000")),
        backend_port=int(os.getenv("BACKEND_PORT", "8000")),
        disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],
    )
