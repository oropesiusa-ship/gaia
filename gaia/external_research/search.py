"""Provider-independent search boundary. Bundled providers need no credentials or network."""
from abc import ABC, abstractmethod
from urllib.parse import urlsplit
from .policy import classify


class SearchProvider(ABC):
    @abstractmethod
    def search(self, request):
        """Return bounded explicit URLs; future network providers need the same authorization policy."""
        raise NotImplementedError


class DirectURLs(SearchProvider):
    def search(self, request):
        order = {"PRIMARY_OFFICIAL": 0, "PRIMARY_SCIENTIFIC": 1, "PRIMARY_REPOSITORY": 2, "SECONDARY_TECHNICAL": 3, "COMMUNITY": 4, "UNKNOWN": 5}
        return sorted(request["payload"]["urls"], key=lambda u: (order[classify(urlsplit(u).hostname, urlsplit(u).path)[0]], u))


class ReplaySearch(SearchProvider):
    def __init__(self, urls):
        self.urls = list(urls)

    def search(self, request):
        # Local search replay may narrow the request, never expand its authorization.
        allowed = set(request["payload"]["urls"])
        if any(u not in allowed for u in self.urls):
            raise ValueError("Replay search URL outside explicit request")
        return list(dict.fromkeys(self.urls))[:request["payload"]["budget"]["max_sources"]]
