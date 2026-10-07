"""One lazy physical-sheet plan for preview, marks, generation and tickets."""
from bisect import bisect_right
from dataclasses import dataclass, replace

from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.template.model import CompositionError

from .model import MediaSpec, PrinterProfile, validate_stock_mapping


def page_role(index,count):
    return "SINGLE" if count==1 else "FIRST" if index==1 else "LAST" if index==count else "CONTINUATION"


@dataclass
class MediaPreflightResult:
    pages:int
    sheets:int
    inserted_blanks:int
    stock_sheets:dict
    configuration_valid:bool=True
    device_validation:str="pending"


@dataclass(frozen=True)
class MediaPageSettings:
    base:EnvelopeSettings
    pages_per_envelope:int
    output_pages_per_envelope:int
    sheets_per_envelope:int

    def __getattr__(self,name):
        return getattr(self.base,name)


@dataclass(frozen=True)
class PrintPage:
    envelope:int
    source_page:int|None
    output_page:int
    print_page:int
    logical_page:int|None
    logical_role:int
    settings:MediaPageSettings
    envelope_count:int
    source_start:int
    stock:str
    reason:str
    sheet:int

    @property
    def role(self):
        return self.logical_role

    def fields(self,job_id="preview"):
        c=self.settings
        return {"JobId":job_id,"EnvelopeSeq":c.sequence(self.envelope),"EnvelopeIndex":str(self.envelope),
            "EnvelopeCount":str(self.envelope_count),"SourcePage":str(self.source_page or ""),
            "LetterPage":str(self.logical_page or ""),"LetterPageCount":str(c.pages_per_envelope),
            "OutputPage":str(self.output_page),"PrintPage":str(self.print_page),"PrintPageCount":str(c.output_pages_per_envelope),
            "SheetNo":str(self.sheet),"SheetCount":str(c.sheets_per_envelope),
            "JobSheetNo":str((self.output_page+1)//2 if c.duplex else self.output_page),
            "Side":"Back" if c.duplex and self.print_page%2==0 else "Front",
            "IsFirstSheet":str(int(self.sheet==1)),"IsLastSheet":str(int(self.sheet==c.sheets_per_envelope)),
            "IsInsertedBlank":str(int(self.source_page is None)),"PageRole":page_role(self.logical_page,c.pages_per_envelope) if self.logical_page else "BLANK",
            "MediaStock":self.stock}


class PrintPlan:
    def __init__(self,base,media,*,page_ids=None,dimensions=None,is_cancelled=None):
        self.base=base
        self.media=MediaSpec.from_dict(media)
        self.settings=replace(base.settings,duplex=self.media.duplex)
        self.source_pages=base.source_pages
        self.excluded_pages=base.excluded_pages
        self.envelopes=base.envelopes
        self.max_source_pages=base.max_source_pages
        self.groups=base.groups
        self.output_starts=[]
        self.patterns={}
        self.output_pages=self.inserted_blanks=self.sheets=0
        self.stock_sheets={}
        self.page_ids=page_ids
        self.dimensions=dimensions
        stocks={s["id"]:s for s in self.media.stocks}
        profile=PrinterProfile.from_dict(self.media.printer_profile)
        requests={}
        for envelope in range(1,self.envelopes+1 if self.groups else 2):
            if is_cancelled and is_cancelled():
                from composition.production.generator import JobCancelled
                raise JobCancelled("Media planning cancelled.")
            start,end,_=base.group(envelope)
            count=end-start+1
            if count not in self.patterns:
                pattern=[]
                last_stock=""
                for logical in range(1,count+1):
                    role=page_role(logical,count)
                    key=role if self.media.mode=="role" else page_ids[logical-1] if self.media.mode=="template" and page_ids else str(logical)
                    stock=self.media.assignments.get(key,self.media.fallback_stock)
                    if not stock:
                        raise CompositionError(f"Media preflight: envelope / record {envelope}, logical page {logical}: no assigned Stock or fallback.")
                    request=validate_stock_mapping(profile,stocks[stock])
                    if profile.backend=="postscript" and request in requests and requests[request]!=stock:
                        raise CompositionError(f"Stocks {requests[request]} and {stock} have identical PostScript selection requests. Configure distinguishable media / paper sources.")
                    requests[request]=stock
                    if dimensions:
                        width,height=dimensions[logical-1]
                        if abs(width-stocks[stock]["width_mm"])>.2 or abs(height-stocks[stock]["height_mm"])>.2:
                            raise CompositionError(f"Logical page {logical}: size differs from Stock {stock}.")
                    if self.media.duplex and len(pattern)%2 and last_stock!=stock:
                        if self.media.blank_policy=="block":
                            raise CompositionError(f"Media conflict: envelope / record {envelope}, logical pages {logical-1} and {logical} require {last_stock} / {stock} on the same sheet. Front and back must use the same Stock. For four duplex pages, assign pages 1/2 to Stock A and pages 3/4 to Stock B, or explicitly select blank-back insertion (adds pages).")
                        pattern.append((None,logical-2,last_stock,"Confirmed media-change blank back"))
                    pattern.append((logical,logical-1,stock,"Rule "+key if key in self.media.assignments else "Explicit fallback"))
                    last_stock=stock
                if self.media.duplex and len(pattern)%2:
                    pattern.append((None,count-1,last_stock,"Envelope-end blank back"))
                self.patterns[count]=pattern
            pattern=self.patterns[count]
            self.output_starts.append(self.output_pages+1)
            self.output_pages+=len(pattern)
            self.inserted_blanks+=len(pattern)-count
            self.sheets+=len(pattern)//2 if self.media.duplex else len(pattern)
            for index,item in enumerate(pattern):
                if not self.media.duplex or index%2==0:
                    self.stock_sheets[item[2]]=self.stock_sheets.get(item[2],0)+1
        if not self.groups:
            self.output_pages*=self.envelopes
            self.inserted_blanks*=self.envelopes
            self.sheets*=self.envelopes
            self.stock_sheets={key:value*self.envelopes for key,value in self.stock_sheets.items()}
            self.output_starts=[]

    def group(self,envelope):
        start,end,_=self.base.group(envelope)
        output=self.output_starts[envelope-1] if self.groups else (envelope-1)*len(self.patterns[end-start+1])+1
        return start,end,output

    def settings_for(self,envelope):
        start,end,_=self.group(envelope)
        count=end-start+1
        size=len(self.patterns[count])
        return MediaPageSettings(self.settings,count,size,size//2 if self.media.duplex else size)

    def page(self,envelope,print_page):
        start,end,output=self.group(envelope)
        settings=self.settings_for(envelope)
        if type(print_page) is not int or not 1<=print_page<=settings.output_pages_per_envelope:
            raise CompositionError("Print page is out of range.")
        logical,role,stock,reason=self.patterns[end-start+1][print_page-1]
        return PrintPage(envelope,start+logical-1 if logical else None,output+print_page-1,print_page,logical,role,
            settings,self.envelopes,start,stock,reason,(print_page+1)//2 if settings.duplex else print_page)

    def output_page(self,number):
        if type(number) is not int or not 1<=number<=self.output_pages:
            raise CompositionError("Output page is out of range.")
        if not self.groups:
            envelope,index=divmod(number-1,len(self.patterns[self.settings.pages_per_envelope]))
            return self.page(envelope+1,index+1)
        envelope=bisect_right(self.output_starts,number)
        return self.page(envelope,number-self.output_starts[envelope-1]+1)

    def pages(self):
        for envelope in range(1,self.envelopes+1):
            for index in range(1,self.settings_for(envelope).output_pages_per_envelope+1):
                yield self.page(envelope,index)

    def envelope_row(self,envelope,status):
        start,end,output=self.group(envelope)
        cfg=self.settings_for(envelope)
        return [envelope,cfg.sequence(envelope),start,end,output,output+cfg.output_pages_per_envelope-1,
                cfg.pages_per_envelope,cfg.output_pages_per_envelope,cfg.sheets_per_envelope,status]

    def preflight(self):
        return MediaPreflightResult(self.output_pages,self.sheets,self.inserted_blanks,dict(self.stock_sheets))


def build_print_plan(template,count,*,is_cancelled=None):
    media=MediaSpec.from_dict(template.media)
    base=EnvelopePlan(count*len(template.pages),EnvelopeSettings(pages_per_envelope=len(template.pages),duplex=media.duplex,digits=18))
    return PrintPlan(base,template.media,page_ids=[p.id for p in template.pages],
        dimensions=[(p.width_mm,p.height_mm) for p in template.pages],is_cancelled=is_cancelled) if media.enabled else base


def overlay_plan(spec,*,is_cancelled=None):
    media=MediaSpec.from_dict(spec.media)
    base=EnvelopePlan(spec.source.pages,spec.settings)
    if not media.enabled:
        return base
    dimensions=[(spec.source.geometries[0 if spec.source.geometry_mode=="uniform" else index]["width_pt"]*25.4/72,
                 spec.source.geometries[0 if spec.source.geometry_mode=="uniform" else index]["height_pt"]*25.4/72)
                for index in range(base.max_source_pages)]
    return PrintPlan(base,spec.media,dimensions=dimensions,is_cancelled=is_cancelled)


def validate_media(plan):
    return plan.preflight() if isinstance(plan,PrintPlan) else None


def preview_plan(spec):
    """Keep a repairable project open when its saved physical media rules conflict."""
    try:
        return overlay_plan(spec)
    except CompositionError as exc:
        plan=EnvelopePlan(spec.source.pages,spec.settings)
        plan.media_error=str(exc)
        return plan
