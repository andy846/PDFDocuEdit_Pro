"""Offline Canon JDF page programming and complete page/media reconciliation."""
import csv
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree as ET

from composition.production.generator import check_cancel
from composition.template.model import CompositionError

from .model import FAMILIES, MediaSpec, PrinterProfile

NS="http://www.CIP4.org/JDFSchema_1_1"
OCE="http://www.oce.com/JDF_Extension/1_00"
ET.register_namespace("",NS)
ET.register_namespace("oce",OCE)
HEADERS=["File page","Global output page","Record / envelope","Source page","Logical page","Page role",
         "Sheet in record","Side","Stock","Reason"]


def plan_rows(plan):
    for page in plan.pages():
        values=page.fields()
        yield [page.output_page,page.output_page,page.envelope,page.source_page or "",values["LetterPage"],
               values["PageRole"],values["SheetNo"],values["Side"],page.stock,page.reason]


def export_print_package(directory,plan,pdf_name="production.pdf",*,is_cancelled=None,write_ticket=True):
    return export_rows(directory,plan.media.to_dict(),plan_rows(plan),plan.output_pages,pdf_name,is_cancelled=is_cancelled,write_ticket=write_ticket)


def export_rows(directory,media,rows,expected_pages,pdf_name,*,is_cancelled=None,write_ticket=True):
    spec=MediaSpec.from_dict(media)
    profile=PrinterProfile.from_dict(spec.printer_profile)
    directory=Path(directory)
    database=directory/"media-plan.sqlite"
    database.unlink(missing_ok=True)
    stock_sheets=Counter()
    with closing(sqlite3.connect(database)) as db, (directory/"media-plan.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        db.execute("CREATE TABLE pages(file_page INTEGER PRIMARY KEY,global_page INTEGER,record INTEGER,source_page,logical_page,role TEXT,sheet,side TEXT,stock TEXT,reason TEXT)")
        writer=csv.writer(stream)
        writer.writerow(HEADERS)
        count=0
        pending_front=None
        for row in rows:
            check_cancel(is_cancelled)
            count+=1
            if len(row)!=10 or row[0]!=count or row[8] not in {s["id"] for s in spec.stocks}:
                raise CompositionError("Media reconciliation: invalid / missing output page or stock.")
            if spec.duplex:
                if count%2:
                    if row[7]!="Front":
                        raise CompositionError("Duplex package must begin each physical sheet on its front.")
                    pending_front=(row[2],row[6],row[8])
                elif row[7]!="Back" or pending_front!=(row[2],row[6],row[8]):
                    raise CompositionError("Media reconciliation: front/back Stock or record conflict.")
            if row[7]=="Front":
                stock_sheets[row[8]]+=1
            db.execute("INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?)",row)
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in row])
        if count!=expected_pages or (spec.duplex and count%2):
            raise CompositionError("Media reconciliation: page count or duplex pairing mismatch.")
        db.commit()
        ticket=_ticket(spec,profile,db,is_cancelled=is_cancelled) if write_ticket else b""
    if len(ticket)>profile.max_ticket_bytes:
        raise CompositionError("Canon reference ticket exceeds the configured size limit. Reduce complete records / envelopes per split file.")
    check_cancel(is_cancelled)
    if write_ticket:
        (directory/"default_ticket.jdf").write_bytes(ticket)
    (directory/"media-definition.json").write_text(json.dumps(spec.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"pages":count,"sheets":sum(stock_sheets.values()),"stock_sheets":dict(stock_sheets),
             "printer":FAMILIES[profile.family],"controller_version":profile.controller_version,"device_validation":"pending",
             "pdf":pdf_name,"ticket":"default_ticket.jdf" if write_ticket else ""}
    (directory/"media-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    with (directory/"media-summary.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["Stock","Required sheets","Device validation"])
        writer.writerows((name,count,"pending") for name,count in sorted(stock_sheets.items()))
    (directory/"SUBMISSION.txt").write_text(
        "CANON REFERENCE PACKAGE - DEVICE VALIDATION PENDING\n"
        "PDF: "+pdf_name+"\n"
        "Load default_ticket.jdf using your PRISMAsync ticket editor and inspect page programming before a proof print.\n"
        "Hotfolder tickets apply to the hotfolder: do not mix packages or replace a ticket while another job is pending.\n"
        "An automated workflow may override the ticket. Check Overrule job ticket and disable banner / trailer / imposition changes for this proof.\n"
        "Map Stock names / Catalog IDs to loaded media on the DFE. No tray availability was queried.\n"
        "This is an offline hotfolder ticket; it is not a JMF submission with a PDF URL.\n",encoding="utf-8")
    return summary


def _ticket(spec,profile,db,*,is_cancelled=None):
    budget=[0]
    def node(parent,name,**attributes):
        budget[0]+=2*len(name)+8+sum(len(str(k))+len(str(v))+4 for k,v in attributes.items())
        if budget[0]>profile.max_ticket_bytes:
            raise CompositionError("Canon reference ticket exceeds the configured size limit. Split output into fewer complete records / envelopes per file.")
        return ET.SubElement(parent,"{"+NS+"}"+name,{k:str(v) for k,v in attributes.items()})
    root=ET.Element("{"+NS+"}JDF",{"ID":"media_job","Type":"Combined","Types":"LayoutPreparation DigitalPrinting",
        "Category":"DigitalPrinting","Version":"1.3","Status":"Waiting","Activation":"Active"})
    node(root,"Comment",Name="Instruction").text="Reference profile - inspect Media Catalog mappings and proof print before production."
    pool=node(root,"ResourcePool")
    layout=node(pool,"LayoutPreparationParams",ID="layout",Class="Parameter",Status="Available",
                Sides="TwoSidedFlipY" if spec.duplex else "OneSided")
    params=node(pool,"DigitalPrintingParams",ID="print",Class="Parameter",Status="Available",PartIDKeys="RunIndex")
    links=node(root,"ResourceLinkPool")
    node(links,"LayoutPreparationParamsLink",rRef=layout.attrib["ID"],Usage="Input")
    node(links,"DigitalPrintingParamsLink",rRef="print",Usage="Input")
    for stock in spec.stocks:
        check_cancel(is_cancelled)
        if not db.execute("SELECT 1 FROM pages WHERE stock=? LIMIT 1",(stock["id"],)).fetchone():
            continue
        mapping=profile.mappings.get(stock["id"],{})
        if not mapping.get("name") and not mapping.get("catalog_id"):
            raise CompositionError("Missing Media Catalog mapping: "+stock["id"])
        attrs={"ID":"media_"+stock["id"],"Class":"Consumable","Status":"Available",
               "Dimension":f"{stock['width_mm']*72/25.4:.5f} {stock['height_mm']*72/25.4:.5f}","Weight":stock["weight_gsm"]}
        if mapping.get("name"):
            attrs["DescriptiveName"]=mapping["name"]
        if mapping.get("catalog_id"):
            attrs["DeviceProductID"]=mapping["catalog_id"]
        resource=node(pool,"Media",**attrs)
        # Bound each range-list attribute; do not construct one enormous RunIndex string.
        ranges=[]
        start=end=None
        def emit(ranges=ranges,resource=resource):
            if ranges:
                part=node(params,"DigitalPrintingParams",RunIndex=" ".join(ranges))
                node(part,"MediaRef",rRef=resource.attrib["ID"])
                ranges.clear()
        for (page,) in db.execute("SELECT file_page-1 FROM pages WHERE stock=? ORDER BY file_page",(stock["id"],)):
            if page%1000==0:
                check_cancel(is_cancelled)
            if start is None:
                start=end=page
            elif page==end+1:
                end=page
            else:
                ranges.append(str(start) if start==end else f"{start} ~ {end}")
                start=end=page
                if sum(len(s)+1 for s in ranges)>700:
                    emit()
        if start is not None:
            ranges.append(str(start) if start==end else f"{start} ~ {end}")
        emit()
        node(links,"MediaLink",rRef=resource.attrib["ID"],Usage="Input")
    result=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    validate_ticket(result,db.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
    return result


def validate_ticket(data,pages):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise CompositionError("External XML declarations are prohibited.")
    root=ET.fromstring(data)
    ids=[item.attrib["ID"] for item in root.iter() if "ID" in item.attrib]
    if len(ids)!=len(set(ids)) or any(item.attrib["rRef"] not in ids for item in root.iter() if "rRef" in item.attrib):
        raise CompositionError("JDF resource references are invalid.")
    ranges=[]
    for item in root.iter("{"+NS+"}DigitalPrintingParams"):
        tokens=item.attrib.get("RunIndex","").split()
        index=0
        while index<len(tokens):
            start=end=int(tokens[index])
            index+=1
            if index<len(tokens) and tokens[index]=="~":
                end=int(tokens[index+1])
                index+=2
            if not 0<=start<=end<pages:
                raise CompositionError("JDF page range exceeds the output PDF.")
            ranges.append((start,end))
    cursor=0
    for start,end in sorted(ranges):
        if start!=cursor:
            raise CompositionError("JDF media assignments overlap or omit pages.")
        cursor=end+1
    if cursor!=pages:
        raise CompositionError("JDF media assignments do not cover the PDF.")
