"""Lazy, one-based source/output/sheet mapping; no rendered-page accumulation."""
from __future__ import annotations

from dataclasses import dataclass

from composition.template.model import CompositionError

from .model import EnvelopeSettings

SYSTEM_FIELDS = frozenset({"JobId", "EnvelopeSeq", "EnvelopeIndex", "EnvelopeCount", "SourcePage",
                          "LetterPage", "LetterPageCount", "OutputPage", "PrintPage", "PrintPageCount",
                          "SheetNo", "SheetCount", "Side", "IsFirstSheet", "IsLastSheet", "IsInsertedBlank"})
SCOPES = ("all_source", "all_output", "first", "last", "front", "letter_page")


@dataclass(frozen=True)
class PagePlan:
    envelope: int
    source_page: int | None
    output_page: int
    print_page: int
    settings: EnvelopeSettings
    envelope_count: int

    @property
    def role(self):
        return (self.print_page-1 if self.source_page is not None else self.settings.pages_per_envelope-1)

    def fields(self, job_id="preview"):
        cfg = self.settings
        sheet = (self.print_page+1)//2 if cfg.duplex else self.print_page
        return {"JobId": job_id, "EnvelopeSeq": cfg.sequence(self.envelope),
                "EnvelopeIndex": str(self.envelope), "EnvelopeCount": str(self.envelope_count),
                "SourcePage": str(self.source_page or ""),
                "LetterPage": str(self.print_page) if self.source_page is not None else "",
                "LetterPageCount": str(cfg.pages_per_envelope), "OutputPage": str(self.output_page),
                "PrintPage": str(self.print_page), "PrintPageCount": str(cfg.output_pages_per_envelope),
                "SheetNo": str(sheet), "SheetCount": str(cfg.sheets_per_envelope),
                "Side": "Back" if cfg.duplex and self.print_page % 2 == 0 else "Front",
                "IsFirstSheet": str(int(sheet == 1)), "IsLastSheet": str(int(sheet == cfg.sheets_per_envelope)),
                "IsInsertedBlank": str(int(self.source_page is None))}


def applies(scope, fields, letter_page=1):
    if scope == "all_source":
        return fields["IsInsertedBlank"] == "0"
    if scope == "all_output":
        return True
    if scope == "first":
        return fields["LetterPage"] == "1"
    if scope == "last":
        return fields["LetterPage"] == fields["LetterPageCount"]
    if scope == "front":
        return fields["Side"] == "Front"
    if scope == "letter_page":
        return fields["LetterPage"] == str(letter_page)
    raise CompositionError("Unsupported overlay scope.")


class EnvelopePlan:
    def __init__(self, source_pages, settings):
        settings.validate()
        if type(source_pages) is not int or source_pages < 1:
            raise CompositionError("Source PDF must contain at least one page.")
        self.settings, self.source_pages = settings, source_pages
        count, remainder = divmod(source_pages, settings.pages_per_envelope)
        if remainder:
            raise CompositionError(f"{source_pages} source pages cannot form complete {settings.pages_per_envelope}-page "
                                   f"envelopes: envelope {count+1} contains only {remainder} page(s).")
        self.envelopes = count
        settings.sequence(count)
        self.output_pages = count*settings.output_pages_per_envelope
        self.inserted_blanks = self.output_pages-source_pages
        self.sheets = count*settings.sheets_per_envelope

    def page(self, envelope, print_page):
        cfg = self.settings
        if type(envelope) is not int or not 1 <= envelope <= self.envelopes:
            raise CompositionError("Envelope is out of range.")
        if type(print_page) is not int or not 1 <= print_page <= cfg.output_pages_per_envelope:
            raise CompositionError("Envelope page is out of range.")
        source = (envelope-1)*cfg.pages_per_envelope + print_page if print_page <= cfg.pages_per_envelope else None
        return PagePlan(envelope, source, (envelope-1)*cfg.output_pages_per_envelope+print_page,
                        print_page, cfg, self.envelopes)

    def pages(self):
        for envelope in range(1, self.envelopes+1):
            for page in range(1, self.settings.output_pages_per_envelope+1):
                yield self.page(envelope, page)
