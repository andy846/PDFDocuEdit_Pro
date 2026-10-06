"""Strict linear graphs: canvas positions are separate from executable settings."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field

from composition.template.model import CompositionError

from .registry import EXTRA_KINDS, MEDIA_KINDS, REGISTRY, validate_chain

KINDS = ("input", "merge", "extract", "group", "review", "overlay", "output")
MAIL_KINDS = ("data", "mapping", "template", "sequences", "mail_review", "compose", "reports")
LABELS = {"input":"PDF Input", "merge":"Merge PDFs", "extract":"Extract Regions",
          "group":"Group Mailpieces", "review":"Review", "overlay":"Overlay", "output":"Validate & Output",
          "data":"Data Input", "mapping":"Field Mapping", "template":"Letter Template",
          "sequences":"Fields & Sequences", "mail_review":"Preview & Review", "compose":"Compose",
          "reports":"Validate & Reports"}
LABELS.update({k: REGISTRY[k].label for k in EXTRA_KINDS})


@dataclass
class WorkflowNode:
    kind: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    x: float = 0
    y: float = 0
    params: dict = field(default_factory=dict)


@dataclass
class WorkflowSpec:
    name: str = "Untitled workflow"
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[list[str]] = field(default_factory=list)
    workflow_version: int = 1
    project_kind: str = "pdf_workflow"

    @classmethod
    def default(cls):
        nodes=[WorkflowNode(k,x=(i%3)*215,y=(i//3)*150) for i,k in enumerate(k for k in KINDS if k!="merge")]
        nodes[0].params={"paths":[]}
        nodes[1].params={"regions":[],"version":1}
        nodes[2].params={"method":"fixed","pages":1,"field":"","pattern":"Page {CURRENT} of {TOTAL}"}
        return cls(nodes=nodes,edges=[[a.id,b.id] for a,b in zip(nodes,nodes[1:],strict=False)])

    @classmethod
    def mail_merge(cls):
        nodes = [WorkflowNode(k, x=(i % 3)*230, y=(i // 3)*150) for i, k in enumerate(MAIL_KINDS)]
        return cls(name="Mail Merge Production", nodes=nodes,
                   edges=[[a.id,b.id] for a,b in zip(nodes,nodes[1:],strict=False)],
                   workflow_version=2, project_kind="mail_merge_workflow")

    @property
    def kinds(self):
        base=MAIL_KINDS if self.project_kind=="mail_merge_workflow" else KINDS
        if self.workflow_version<3:
            return base
        extra=EXTRA_KINDS if self.workflow_version>=4 else tuple(k for k in EXTRA_KINDS if k not in MEDIA_KINDS)
        return base+extra

    def upgraded(self,version=3):
        result=copy.deepcopy(self)
        result.workflow_version=max(self.workflow_version,version)
        return result

    def allowed_next(self, kind):
        if self.workflow_version>=3:
            if kind in ("output","reports"):
                return set()
            definition=REGISTRY[kind]
            outputs=(definition.output,) if definition.output else definition.inputs
            compatible={k for k in self.kinds if k not in ("input","data") and
                        any(REGISTRY[k].accepts(t) for t in outputs)}
            if kind not in EXTRA_KINDS:
                legacy=copy.copy(self)
                legacy.workflow_version=2 if self.project_kind=="mail_merge_workflow" else 1
                compatible&=legacy.allowed_next(kind)|set(EXTRA_KINDS)
            return compatible
        if self.project_kind=="mail_merge_workflow":
            index=MAIL_KINDS.index(kind)
            return set(MAIL_KINDS[index+1:index+2])
        return {"input":{"merge","extract"},"merge":{"extract"},"extract":{"group"},
                "group":{"review"},"review":{"overlay","output"},"overlay":{"output"}}.get(kind,set())

    @classmethod
    def from_dict(cls, raw):
        try:
            result=cls(**{**copy.deepcopy(raw),"nodes":[WorkflowNode(**n) for n in raw["nodes"]]})
            result.validate()
            return result
        except (TypeError, KeyError) as exc:
            raise CompositionError("Invalid workflow structure") from exc

    def validate(self):
        if (type(self.workflow_version) is not int or self.workflow_version not in (1,2,3,4)
                or self.project_kind not in ("pdf_workflow","mail_merge_workflow")
                or (self.project_kind=="mail_merge_workflow" and self.workflow_version not in (2,3,4))
                or not isinstance(self.name,str) or len(self.name)>200 or not isinstance(self.nodes,list)
                or not 1<=len(self.nodes)<=(64 if self.workflow_version>=3 else 7)
                or not isinstance(self.edges,list) or len(self.edges)>(63 if self.workflow_version>=3 else 6)):
            raise CompositionError("Unsupported workflow format or graph size.")
        ids=set()
        kinds=set()
        for n in self.nodes:
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",n.id) or n.id in ids or n.kind not in self.kinds
                    or (n.kind in kinds and not (self.workflow_version>=3 and REGISTRY[n.kind].repeatable))
                    or not isinstance(n.params,dict)
                    or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in (n.x,n.y))):
                raise CompositionError("Invalid/duplicate workflow node.")
            ids.add(n.id)
            kinds.add(n.kind)
            if self.workflow_version>=3:
                REGISTRY[n.kind].validate_options(n.params)
        for edge in self.edges:
            if not isinstance(edge,list) or len(edge)!=2 or any(v not in ids for v in edge):
                raise CompositionError("Invalid workflow connection.")
        if len({tuple(e) for e in self.edges})!=len(self.edges):
            raise CompositionError("Duplicate connection.")
        # Disconnected drafts can be saved; execution requires a complete valid chain.
        incoming, outgoing={},{}
        for a,b in self.edges:
            if a in outgoing or b in incoming or a==b:
                raise CompositionError("First release supports a single chain, without branches or loops.")
            outgoing[a]=b
            incoming[b]=a
            left=next(n.kind for n in self.nodes if n.id==a)
            right=next(n.kind for n in self.nodes if n.id==b)
            if right not in self.allowed_next(left):
                raise CompositionError(f"{LABELS[left]} cannot connect to {LABELS[right]}.")
        for identity in ids:
            visited=set()
            cursor=identity
            while cursor in outgoing:
                if cursor in visited:
                    raise CompositionError("Workflow loops are not supported.")
                visited.add(cursor)
                cursor=outgoing[cursor]
        if self.workflow_version>=3:
            root=self.node("data" if self.project_kind=="mail_merge_workflow" else "input")
            if root:
                path=[]
                lookup={n.id:n for n in self.nodes}
                cursor=root
                while cursor:
                    path.append(cursor)
                    cursor=lookup.get(outgoing.get(cursor.id))
                validate_chain(path,self.project_kind)

    def chain(self):
        self.validate()
        kinds={n.kind:n for n in self.nodes}
        required=set(MAIL_KINDS) if self.project_kind=="mail_merge_workflow" else {"input","extract","group","review","output"}
        if not required<=kinds.keys():
            if self.project_kind=="mail_merge_workflow":
                raise CompositionError("Connect every Mail Merge step, from Data Input to Validate & Reports.")
            raise CompositionError("Connect PDF Input, Extract Regions, Group Mailpieces, Review and Output.")
        edges=dict(self.edges)
        current=kinds["data" if self.project_kind=="mail_merge_workflow" else "input"]
        chain=[]
        while current:
            chain.append(current)
            following=edges.get(current.id)
            current=next((n for n in self.nodes if n.id==following),None)
        if len(chain)!=len(self.nodes) or chain[-1].kind!=("reports" if self.project_kind=="mail_merge_workflow" else "output"):
            raise CompositionError("Connect every node into one complete input-to-output chain.")
        if self.workflow_version>=3:
            validate_chain(chain,self.project_kind)
        return chain

    def execution_prefix(self, node_id):
        """A connected, typed source-to-target path; no terminal node required."""
        self.validate()
        root=self.node("data" if self.project_kind=="mail_merge_workflow" else "input")
        if root is None:
            raise CompositionError("Add the workflow's source step before checking.")
        lookup={node.id:node for node in self.nodes}
        edges=dict(self.edges)
        path=[]
        cursor=root
        while cursor:
            path.append(cursor)
            if cursor.id==node_id:
                validate_chain(path,self.project_kind)
                return path
            cursor=lookup.get(edges.get(cursor.id))
        raise CompositionError("Connect the selected step to the source before checking.")

    def insert_after(self, identity, node):
        result=copy.deepcopy(self)
        following=next((b for a,b in result.edges if a==identity),None)
        result.nodes.append(copy.deepcopy(node))
        result.edges=[e for e in result.edges if e[0]!=identity]
        result.edges.append([identity,node.id])
        if following:
            result.edges.append([node.id,following])
        result.validate()
        root=result.node("data" if result.project_kind=="mail_merge_workflow" else "input")
        edges=dict(result.edges)
        tail=root
        while tail and tail.id in edges:
            tail=next(n for n in result.nodes if n.id==edges[tail.id])
        if tail:
            result.execution_prefix(tail.id)
        return result

    def reorder(self, identities):
        if len(identities)!=len(self.nodes) or set(identities)!={n.id for n in self.nodes}:
            raise CompositionError("Reordering must include every node exactly once.")
        result=copy.deepcopy(self)
        result.edges=[[a,b] for a,b in zip(identities,identities[1:],strict=False)]
        result.chain()
        return result

    def node(self, kind):
        return next((n for n in self.nodes if n.kind==kind),None)

    def to_dict(self):
        return asdict(self)

    def fingerprint(self):
        value=self.to_dict()
        for n in value["nodes"]:
            n.pop("x")
            n.pop("y")
        return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


@dataclass
class WorkflowRun:
    fingerprint: str = ""
    statuses: dict = field(default_factory=dict)
    signatures: dict = field(default_factory=dict)
    source: str = ""
    database: str = ""
    groups: list[list[int]] = field(default_factory=list)
    accepted: bool = False
    output: dict = field(default_factory=dict)
    error: str = ""
    data_set: str = ""
    data_steps: list = field(default_factory=list)
    data_summary: dict = field(default_factory=dict)
    page_pipeline_signature: str = ""
