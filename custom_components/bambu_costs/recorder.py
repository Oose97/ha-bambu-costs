"""Keep the bulky list attributes out of the recorder database.

The tag library and job log carry their whole payload in an attribute. Without
this the recorder would store a fresh copy on every state write and the
database would balloon — the YAML setup needed a hand-written `recorder:`
exclusion to avoid exactly that.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback


@callback
def exclude_attributes(hass: HomeAssistant) -> set[str]:
    """Attributes never worth recording."""
    return {"data", "slots"}
