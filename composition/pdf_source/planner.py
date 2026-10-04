"""Lazy, one-based source/output/sheet mapping; no rendered-page accumulation."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace

from composition.template.model import CompositionError

from .model import EnvelopeSettings

SYSTEM_FIELDS = frozenset({"JobId", "EnvelopeSeq", "EnvelopeIndex", "EnvelopeCount", "SourcePage",
                          "LetterPage", "LetterPageCount", "OutputPage", "PrintPage", "PrintPageCount",
                          "SheetNo", "SheetCount", "Side", "IsFirstSheet", "IsLastSheet", "IsInsertedBlank", "PageRole", "MediaStock"})
SCOPES = ("all_source", "all_output", "first", "last", "front", "letter_page")


@dataclass(frozen=True)
class PagePlan:
    envelope: int
    source_page: int | None
    output_page: int
    print_page: int
    settings: EnvelopeSettings
    envelope_count: int
    source_start: int = 1

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
                "IsInsertedBlank": str(int(self.source_page is None)),
                "PageRole":("BLANK" if self.source_page is None else "SINGLE" if cfg.pages_per_envelope==1
                            else "FIRST" if self.print_page==1 else "LAST" if self.print_page==cfg.pages_per_envelope else "CONTINUATION"),
                "MediaStock":""}


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
        self.groups = settings.groups
        self.excluded_pages = len(settings.excluded_pages)
        self.output_starts = []
        self.output_pages = self.inserted_blanks = self.sheets = 0
        if self.groups:
            excluded = set(settings.excluded_pages)
            cursor = 1
            for start, end in self.groups:
                while cursor in excluded:
                    cursor += 1
                if start != cursor or end > source_pages:
                    raise CompositionError("Boundaries overlap, omit pages or exceed the PDF. Review detection.")
                excluded_index = bisect_left(settings.excluded_pages, start)
                if excluded_index < len(settings.excluded_pages) and settings.excluded_pages[excluded_index] <= end:
                    raise CompositionError("A separator page is also assigned to an envelope.")
                self.output_starts.append(self.output_pages + 1)
                count = end-start+1
                cfg = replace(settings, pages_per_envelope=count)
                self.output_pages += cfg.output_pages_per_envelope
                self.inserted_blanks += cfg.output_pages_per_envelope-count
                self.sheets += cfg.sheets_per_envelope
                cursor = end+1
            while cursor in excluded:
                cursor += 1
            if cursor != source_pages+1 or any(n > source_pages for n in excluded):
                raise CompositionError("Every source page must belong to an envelope or an explicit separator exclusion.")
            self.envelopes = len(self.groups)
        else:
            count, remainder = divmod(source_pages, settings.pages_per_envelope)
            if remainder:
                raise CompositionError(f"{source_pages} source pages cannot form complete {settings.pages_per_envelope}-page "
                                       f"envelopes: envelope {count+1} contains only {remainder} page(s).")
            self.envelopes = count
            self.output_pages = count*settings.output_pages_per_envelope
            self.inserted_blanks = self.output_pages-source_pages
            self.sheets = count*settings.sheets_per_envelope
        self.max_source_pages = max((end-start+1 for start, end in self.groups), default=settings.pages_per_envelope)
        settings.sequence(self.envelopes)

    def group(self, envelope):
        if type(envelope) is not int or not 1 <= envelope <= self.envelopes:
            raise CompositionError("Envelope is out of range.")
        if self.groups:
            start, end = self.groups[envelope-1]
            return start, end, self.output_starts[envelope-1]
        cfg = self.settings
        return ((envelope-1)*cfg.pages_per_envelope+1, envelope*cfg.pages_per_envelope,
                (envelope-1)*cfg.output_pages_per_envelope+1)

    def settings_for(self, envelope):
        start, end, _output = self.group(envelope)
        return replace(self.settings, pages_per_envelope=end-start+1)

    def page(self, envelope, print_page):
        start, end, output_start = self.group(envelope)
        cfg = self.settings_for(envelope)
        if type(print_page) is not int or not 1 <= print_page <= cfg.output_pages_per_envelope:
            raise CompositionError("Envelope page is out of range.")
        source = start+print_page-1 if print_page <= cfg.pages_per_envelope else None
        return PagePlan(envelope, source, output_start+print_page-1, print_page, cfg, self.envelopes, start)

    def output_page(self, output_page):
        if type(output_page) is not int or not 1 <= output_page <= self.output_pages:
            raise CompositionError("Output page is out of range.")
        envelope = (bisect_right(self.output_starts, output_page) if self.groups else
                    (output_page-1)//self.settings.output_pages_per_envelope+1)
        _start, _end, first = self.group(envelope)
        return self.page(envelope, output_page-first+1)

    def envelope_row(self, envelope, status):
        start, end, output_start = self.group(envelope)
        cfg = self.settings_for(envelope)
        return [envelope, cfg.sequence(envelope), start, end, output_start,
                output_start+cfg.output_pages_per_envelope-1, cfg.pages_per_envelope,
                cfg.output_pages_per_envelope, cfg.sheets_per_envelope, status]

    def pages(self):
        for envelope in range(1, self.envelopes+1):
            for page in range(1, self.settings_for(envelope).output_pages_per_envelope+1):
                yield self.page(envelope, page)
