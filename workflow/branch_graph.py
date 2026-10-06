"""v5 bounded routing graph; independent from the Qt designer and linear engine."""
from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass

from composition.template.model import CompositionError

from .model import WorkflowNode, WorkflowSpec
from .registry import DATA_KINDS, REGISTRY
from .transforms import condition, validate_options

BRANCH_KINDS=("for_each","mapping",*DATA_KINDS,"batch_sequence","route","template",
              "media_assignment","mail_review","compose","reports","exceptions","collect")
BRANCH_LABELS={"for_each":"For each Data File","batch_sequence":"Batch Sequence",
               "route":"Route by Condition","exceptions":"Exceptions","collect":"Collect Results"}
COMMON=("mapping",*DATA_KINDS,"batch_sequence")
BRANCH=("template","media_assignment","mail_review","compose","reports")


def edge(source,target,port="out"):
    return {"source":source,"target":target,"port":port}


def default():
    nodes=[WorkflowNode(k,x=i*230,y=0) for i,k in enumerate(("for_each","mapping","batch_sequence","route"))]
    nodes[0].params={"items":[]}
    nodes[2].params={"name":"WorkflowSeq","start":1,"step":1,"padding":6,"prefix":"","suffix":"","scope":"record"}
    nodes[3].params={"routes":[{"id":"letters","name":"Letters","fallback":True}]}
    edges=[edge(a.id,b.id) for a,b in zip(nodes,nodes[1:],strict=False)]
    tail=nodes[-1]
    for i,k in enumerate(("template","mail_review","compose","reports")):
        n=WorkflowNode(k,x=230*i+230,y=180,params={"path":""} if k=="template" else {})
        nodes.append(n)
        edges.append(edge(tail.id,n.id,"letters" if tail.kind=="route" else "out"))
        tail=n
    exceptions=WorkflowNode("exceptions",x=230,y=360)
    collector=WorkflowNode("collect",x=1150,y=180)
    edges += [edge(nodes[3].id,exceptions.id,"exceptions"),edge(tail.id,collector.id),edge(exceptions.id,collector.id)]
    return WorkflowSpec(name="Conditional Mail Merge",workflow_version=5,project_kind="mail_merge_workflow",
                        nodes=nodes+[exceptions,collector],edges=edges)


def valid_id(value):
    return isinstance(value,str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}",value))


def validate(spec):
    if (spec.project_kind!="mail_merge_workflow" or not isinstance(spec.name,str) or len(spec.name)>200
            or not isinstance(spec.nodes,list) or not 1<=len(spec.nodes)<=64
            or not isinstance(spec.edges,list) or len(spec.edges)>128):
        raise CompositionError("Invalid v5 Mail Merge graph.")
    lookup={}
    for n in spec.nodes:
        if (not valid_id(n.id) or n.id in lookup or n.kind not in BRANCH_KINDS or not isinstance(n.params,dict)
                or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in (n.x,n.y))):
            raise CompositionError("Invalid v5 node identity or settings.")
        lookup[n.id]=n
        if n.kind in DATA_KINDS or n.kind=="media_assignment":
            REGISTRY[n.kind].validate_options(n.params)
        if n.kind=="batch_sequence":
            validate_options("running_sequence",n.params)
            if n.params.get("scope","record")!="record" or n.params.get("step",1)<1:
                raise CompositionError("Batch Sequence needs record scope and a positive increment.")
        if n.kind=="for_each":
            items=n.params.get("items",[])
            if not isinstance(items,list) or len(items)>10000:
                raise CompositionError("Use at most 10,000 source items.")
            seen=set()
            for item in items:
                if (not isinstance(item,dict) or set(item)-{"id","path","options"} or not valid_id(item.get("id"))
                        or item["id"] in seen or not isinstance(item.get("path"),str)
                        or not 1<=len(item["path"])<=4096 or not isinstance(item.get("options",{}),dict)):
                    raise CompositionError("Source items need stable unique IDs, paths and import options.")
                seen.add(item["id"])
        if n.kind=="route":
            routes=n.params.get("routes",[])
            if not isinstance(routes,list) or not 1<=len(routes)<=12:
                raise CompositionError("Configure 1–12 template routes.")
            names=set()
            fallback=0
            for r in routes:
                if (not isinstance(r,dict) or set(r)-{"id","name","fallback","condition"}
                        or not valid_id(r.get("id")) or r["id"]=="exceptions" or r["id"] in names
                        or not isinstance(r.get("name"),str) or not 1<=len(r["name"])<=100
                        or type(r.get("fallback",False)) is not bool):
                    raise CompositionError("Invalid route name, identity or condition.")
                names.add(r["id"])
                if r.get("fallback"):
                    fallback+=1
                else:
                    options=r.get("condition",{})
                    if not isinstance(options,dict) or not 1<=len(options.get("conditions",[]))<=20:
                        raise CompositionError("A conditional route needs 1–20 conditions.")
                    condition(options)
            if fallback>1:
                raise CompositionError("Only one explicit fallback route is allowed.")
    for kind in ("for_each","mapping","batch_sequence","route","exceptions","collect"):
        if sum(n.kind==kind for n in spec.nodes)>1:
            raise CompositionError("Nested loops/routing and duplicate shared steps are not supported.")
    incoming={k:[] for k in lookup}
    outgoing={k:[] for k in lookup}
    seen=set()
    for e in spec.edges:
        if (not isinstance(e,dict) or set(e)!={"source","target","port"}
                or e["source"] not in lookup or e["target"] not in lookup or not valid_id(e["port"])):
            raise CompositionError("v5 connections require source, target and a named port.")
        a,b=lookup[e["source"]],lookup[e["target"]]
        if (a.id,e["port"]) in seen or a.id==b.id:
            raise CompositionError("Each named output may connect once; self-loops are prohibited.")
        seen.add((a.id,e["port"]))
        incoming[b.id].append(e)
        outgoing[a.id].append(e)
        if a.kind=="route":
            ports={r["id"] for r in a.params["routes"]}
            if not (e["port"]=="exceptions" and b.kind=="exceptions" or e["port"] in ports and b.kind=="template"):
                raise CompositionError("Route ports connect to their template, or the exception sink.")
        elif e["port"]!="out" or not (
                a.kind=="for_each" and b.kind in COMMON or
                a.kind in COMMON and b.kind in (*COMMON,"route") or
                a.kind in ("template","media_assignment") and b.kind in ("media_assignment","mail_review") or
                a.kind=="mail_review" and b.kind=="compose" or a.kind=="compose" and b.kind=="reports" or
                a.kind in ("reports","exceptions") and b.kind=="collect"):
            raise CompositionError(f"{a.kind} cannot connect to {b.kind}.")
    for identity,entries in incoming.items():
        if len(entries)>1 and lookup[identity].kind!="collect":
            raise CompositionError("Only Collect Results accepts multiple incoming paths.")
    visiting=set()
    done=set()
    def walk(identity):
        if identity in visiting:
            raise CompositionError("Cycles and unbounded loops are prohibited.")
        if identity in done:
            return
        visiting.add(identity)
        for e in outgoing[identity]:
            walk(e["target"])
        visiting.remove(identity)
        done.add(identity)
    for identity in lookup:
        walk(identity)


@dataclass
class BranchExecutionPlan:
    common:list
    branches:dict
    route:WorkflowNode|None
    target:WorkflowNode|None=None


def execution_plan(spec,target_id=None):
    validate(spec)
    lookup={n.id:n for n in spec.nodes}
    if target_id is not None and target_id not in lookup:
        raise CompositionError("Inspection target does not exist.")
    root=spec.node("for_each")
    if not root:
        raise CompositionError("Add a For each Data File source.")
    outgoing={}
    for e in spec.edges:
        outgoing.setdefault(e["source"],[]).append(e)
    common=[]
    cursor=root
    while cursor and cursor.kind!="route":
        common.append(cursor)
        if cursor.id==target_id:
            return BranchExecutionPlan(common,{},None,cursor)
        edges=outgoing.get(cursor.id,[])
        cursor=lookup[edges[0]["target"]] if len(edges)==1 else None
    if not cursor or sum(n.kind=="batch_sequence" for n in common)!=1:
        raise CompositionError("Connect sources and one Batch Sequence to Route by Condition.")
    sequence_index=next(i for i,n in enumerate(common) if n.kind=="batch_sequence")
    if any(n.kind in ("clean_fields","create_fields","filter_records","sort_records") for n in common[sequence_index+1:]):
        raise CompositionError("Clean, filter and sort before assigning the batch sequence.")
    branches={}
    visited={n.id for n in common}|{cursor.id}
    for route in cursor.params["routes"]:
        edge_list=[e for e in outgoing.get(cursor.id,[]) if e["port"]==route["id"]]
        path=[]
        n=lookup[edge_list[0]["target"]] if edge_list else None
        while n and n.kind!="collect":
            path.append(n)
            visited.add(n.id)
            if n.id==target_id:
                return BranchExecutionPlan(common,{route["id"]:path},cursor,n)
            edges=outgoing.get(n.id,[])
            n=lookup[edges[0]["target"]] if len(edges)==1 else None
        if (target_id is None or lookup[target_id].kind=="collect") and (not n or [v.kind for v in path if v.kind!="media_assignment"]!=["template","mail_review","compose","reports"]):
            raise CompositionError("Each route needs Template → Review → Compose → Reports → Collect Results.")
        if n:
            visited.add(n.id)
        branches[route["id"]]=path
    exc=spec.node("exceptions")
    collector=spec.node("collect")
    if target_id is not None and target_id in (cursor.id,exc.id if exc else None):
        return BranchExecutionPlan(common,branches,cursor,lookup[target_id])
    if not exc or not collector or not any(e["port"]=="exceptions" and e["target"]==exc.id for e in outgoing.get(cursor.id,[])) or not any(e["target"]==collector.id for e in outgoing.get(exc.id,[])):
        raise CompositionError("Connect the exception sink to Collect Results.")
    visited.update((exc.id,collector.id))
    if (target_id is None or lookup[target_id].kind=="collect") and visited!=set(lookup):
        raise CompositionError("Connect every node to the production graph.")
    if target_id and target_id!=collector.id:
        raise CompositionError("Connect the selected step to its source before checking.")
    return BranchExecutionPlan(common,branches,cursor,collector if target_id else None)


def add_route(spec,name,options=None,fallback=False):
    result=copy.deepcopy(spec)
    route=result.node("route")
    identity=WorkflowNode("template").id
    route.params["routes"].append({"id":identity,"name":name,"fallback":fallback,
                                   **({"condition":options} if not fallback else {})})
    tail=route
    row=len(route.params["routes"])*180
    for i,kind in enumerate(("template","mail_review","compose","reports")):
        n=WorkflowNode(kind,x=230+i*230,y=row,params={"path":""} if kind=="template" else {})
        result.nodes.append(n)
        result.edges.append(edge(tail.id,n.id,identity if tail is route else "out"))
        tail=n
    result.edges.append(edge(tail.id,result.node("collect").id))
    result.validate()
    return result


def child_spec(plan,branch_id):
    result=WorkflowSpec.mail_merge().upgraded(4)
    branch=plan.branches[branch_id]
    for kind in ("compose","reports"):
        original=next((n for n in branch if n.kind==kind),None)
        if original:
            result.node(kind).params=copy.deepcopy(original.params)
    for media in (n for n in branch if n.kind=="media_assignment"):
        n=WorkflowNode("media_assignment",id=media.id,params=copy.deepcopy(media.params))
        result=result.insert_after(result.node("sequences").id,n)
    return result
