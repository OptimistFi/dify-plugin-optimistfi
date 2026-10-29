from typing import Any

from dify_plugin import ToolProvider


class OptimistFiProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        # OptimistFi's endpoint is public: there is no key to check.
        return None
