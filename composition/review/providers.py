"""Bounded audit for the existing headless external-values callback API."""
import hashlib
import json


class ProviderAudit:
    def __init__(self, provider):
        self.provider = provider
        self.capture = False
        self.digest = hashlib.sha256()

    def __call__(self, page):
        values = self.provider(page)
        if self.capture:
            self.digest.update(json.dumps([page.output_page, values], sort_keys=True, ensure_ascii=True,
                                          separators=(",", ":")).encode())
            self.digest.update(b"\n")
        return values
