"""Versioned stock and device contracts; no GUI or executable instructions."""
import math
import re
from dataclasses import asdict, dataclass, field

from composition.template.model import CompositionError

ROLES=("SINGLE","FIRST","CONTINUATION","LAST")
FAMILIES={"vp6000":"varioPRINT 6300 / 6000","i300":"varioPRINT i300","ix":"varioPRINT iX"}
PS_FAMILIES={"generic":"Generic PostScript 3", "canon":"Canon / PRISMAsync",
             "xerox":"Xerox / FreeFlow", "custom":"Other PostScript controller"}


@dataclass
class PrinterProfile:
    profile_version:int=1
    backend:str="canon_prismasync"
    family:str="vp6000"
    controller_version:str="Reference only; actual version not verified"
    validation:str="pending"
    mappings:dict=field(default_factory=dict)
    max_ticket_bytes:int=1048576
    profile_name:str=""
    selection_mode:str="attributes"
    tumble:bool=False
    resolution_dpi:int=600
    emit_media_weight:bool=False

    @classmethod
    def from_dict(cls,raw):
        try:
            profile=cls(**raw)
            if (type(profile.profile_version) is not int or profile.profile_version not in (1,2)
                    or profile.backend not in ("canon_prismasync","postscript")
                    or (profile.backend=="postscript" and profile.profile_version!=2)
                    or profile.family not in (FAMILIES if profile.backend=="canon_prismasync" else FAMILIES|PS_FAMILIES)
                    or profile.validation!="pending" or not isinstance(profile.controller_version,str)
                    or len(profile.controller_version)>200 or type(profile.max_ticket_bytes) is not int
                    or not 1024<=profile.max_ticket_bytes<=1048576 or not isinstance(profile.mappings,dict)
                    or len(profile.mappings)>100 or not isinstance(profile.profile_name,str) or len(profile.profile_name)>100
                    or any(ord(c)<32 for c in profile.profile_name) or profile.selection_mode not in ("attributes","tray")
                    or type(profile.tumble) is not bool or type(profile.emit_media_weight) is not bool
                    or type(profile.resolution_dpi) is not int or profile.resolution_dpi not in (300,600,1200)):
                raise CompositionError("Invalid printer profile. Device validation remains pending.")
            for key,item in profile.mappings.items():
                allowed={"name","catalog_id"} if profile.backend=="canon_prismasync" else {"name","catalog_id","media_type","media_color","media_position"}
                if not valid_id(key) or not isinstance(item,dict) or set(item)-allowed:
                    raise CompositionError("Invalid Stock / printer mapping.")
                for name in allowed-{"media_position"}:
                    value=item.get(name,"")
                    if not isinstance(value,str) or len(value)>40 or any(ord(c)<32 for c in value):
                        raise CompositionError("Media identifiers need up to 40 printable characters.")
                position=item.get("media_position")
                if position is not None and (type(position) is not int or not 0<=position<=9999):
                    raise CompositionError("MediaPosition must be a device paper-source number from 0 to 9999.")
            return profile
        except (TypeError,AttributeError) as exc:
            raise CompositionError("Invalid printer profile.") from exc


def valid_id(value):
    return isinstance(value,str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}",value)


def validate_stock_mapping(profile,stock):
    """Return the effective device request; production requires an explicit mapping."""
    mapping=profile.mappings.get(stock["id"],{})
    if profile.backend=="canon_prismasync":
        if not mapping.get("name") and not mapping.get("catalog_id"):
            raise CompositionError(f"Stock {stock['id']}: configure its Media Catalog mapping.")
        return (mapping.get("name"),mapping.get("catalog_id"))
    if profile.selection_mode=="tray":
        if mapping.get("media_position") is None:
            raise CompositionError(f"Stock {stock['id']}: configure its PostScript MediaPosition (0 is valid).")
        return (stock["width_mm"],stock["height_mm"],mapping["media_position"])
    if not mapping.get("media_type"):
        raise CompositionError(f"Stock {stock['id']}: configure an explicit PostScript MediaType.")
    return (stock["width_mm"],stock["height_mm"],mapping["media_type"],mapping.get("media_color", ""),
            stock["weight_gsm"] if profile.emit_media_weight else None)


@dataclass
class MediaSpec:
    media_version:int=1
    enabled:bool=False
    mode:str="page"
    stocks:list=field(default_factory=list)
    assignments:dict=field(default_factory=dict)
    fallback_stock:str=""
    duplex:bool=False
    blank_policy:str="block"
    printer_profile:dict=field(default_factory=lambda:asdict(PrinterProfile()))

    @classmethod
    def from_dict(cls,raw=None):
        try:
            if raw is not None and not isinstance(raw,dict):
                raise CompositionError("Invalid media specification.")
            spec=cls(**({} if raw is None else raw))
            spec.validate()
            return spec
        except (TypeError,AttributeError) as exc:
            raise CompositionError("Invalid media specification.") from exc

    def validate(self):
        if (self.media_version!=1 or type(self.enabled) is not bool or type(self.duplex) is not bool
                or self.mode not in ("page","role","template") or self.blank_policy not in ("block","insert")
                or not isinstance(self.stocks,list) or len(self.stocks)>100
                or not isinstance(self.assignments,dict) or len(self.assignments)>1000):
            raise CompositionError("Invalid media rules.")
        ids=set()
        for stock in self.stocks:
            if (not isinstance(stock,dict) or set(stock)-{"id","name","width_mm","height_mm","weight_gsm","preprinted"}
                    or not valid_id(stock.get("id")) or stock["id"] in ids
                    or not isinstance(stock.get("name"),str) or not 1<=len(stock["name"])<=100
                    or type(stock.get("preprinted",False)) is not bool):
                raise CompositionError("Stocks need unique stable IDs and names.")
            for name,minimum,maximum in (("width_mm",10,2000),("height_mm",10,2000),("weight_gsm",30,1000)):
                value=stock.get(name)
                if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:
                    raise CompositionError("Invalid stock size or weight.")
            ids.add(stock["id"])
        if self.enabled and not ids:
            raise CompositionError("Define at least one Stock before enabling Media Assignment.")
        for key,value in self.assignments.items():
            valid=(key in ROLES if self.mode=="role" else isinstance(key,str) and key.isascii() and key.isdigit() and 1<=int(key)<=100
                   if self.mode=="page" else isinstance(key,str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}",key)))
            if not valid or value not in ids:
                raise CompositionError("Invalid page rule or unknown Stock.")
        if self.fallback_stock and self.fallback_stock not in ids:
            raise CompositionError("Fallback Stock is not defined.")
        PrinterProfile.from_dict(self.printer_profile)

    def to_dict(self):
        return asdict(self)


def default_media():
    stocks=[{"id":"LH_"+key,"name":"Letterhead "+key,"width_mm":210,"height_mm":297,
             "weight_gsm":80,"preprinted":True} for key in "ABC"]
    return MediaSpec(enabled=True,stocks=stocks,assignments={str(i+1):s["id"] for i,s in enumerate(stocks)},
        printer_profile=asdict(PrinterProfile(mappings={s["id"]:{"name":s["id"],"catalog_id":""} for s in stocks}))).to_dict()
