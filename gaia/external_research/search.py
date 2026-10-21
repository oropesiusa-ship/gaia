"""Provider-independent search boundary. Bundled providers need no credentials or network."""
from abc import ABC, abstractmethod


class SearchProvider(ABC):
    @abstractmethod
    def search(self, request):
        """Return bounded explicit URLs; future network providers need the same authorization policy."""
        raise NotImplementedError


class DirectURLs(SearchProvider):
    def search(self, request):
        return list(request["payload"]["urls"])


class ReplaySearch(SearchProvider):
    def __init__(self, urls):
        self.urls = list(urls)

    def search(self, request):
        # Local search replay may narrow the request, never expand its authorization.
        allowed = set(request["payload"]["urls"])
        if any(u not in allowed for u in self.urls):
            raise ValueError("Replay search URL outside explicit request")
        return list(dict.fromkeys(self.urls))[:request["payload"]["budget"]["max_sources"]]
