"""Demo provider selection. Baseten is the proven default route.

HTW_PROVIDER controls the choice: "meta" or "baseten" select explicitly,
"auto" (default) prefers the proven Baseten route when BASETEN_API_KEY is
present and falls back to Meta Model API when only MODEL_API_KEY (or the
legacy META_MODEL_API_KEY) is present. Only key presence is inspected
here; key values stay with the providers that read them.
"""

import os

from .baseten import BasetenMuseProvider
from .meta_provider import MetaProvider
from .providers import ProviderError

CHOICE_ENV_VAR = "HTW_PROVIDER"


def _meta_key_present():
    return bool(os.environ.get("MODEL_API_KEY") or os.environ.get("META_MODEL_API_KEY"))


def create_provider(image_data_url=None):
    """Create (provider, ui_label) from HTW_PROVIDER and available keys."""
    choice = (os.environ.get(CHOICE_ENV_VAR) or "auto").strip().lower()
    if choice == "meta":
        provider = MetaProvider(image_data_url=image_data_url)
    elif choice == "baseten":
        provider = BasetenMuseProvider(image_data_url=image_data_url)
    elif choice == "auto":
        if os.environ.get("BASETEN_API_KEY"):
            provider = BasetenMuseProvider(image_data_url=image_data_url)
        elif _meta_key_present():
            provider = MetaProvider(image_data_url=image_data_url)
        else:
            raise ProviderError(
                "No provider key found: set BASETEN_API_KEY or MODEL_API_KEY "
                "(HTW_PROVIDER=auto)."
            )
    else:
        raise ProviderError(f"Unknown HTW_PROVIDER={choice!r}: use auto, meta, or baseten.")
    if isinstance(provider, BasetenMuseProvider):
        label = "Meta Muse Spark Open via Baseten"
    else:
        label = f"Meta Model API ({provider.model})"
    return provider, label
