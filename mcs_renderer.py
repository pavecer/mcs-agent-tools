"""Backward-compatible exports for moved module."""

from toolkit.mcs import renderer as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


def render_knowledge_sources_and_tools(profile):
    """Proxy call that honours monkeypatched wrapper-level URL checker."""
    _impl._check_public_url = globals().get("_check_public_url", _impl._check_public_url)
    return _impl.render_knowledge_sources_and_tools(profile)
