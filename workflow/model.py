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

KINDS = ("input", "merge", "extract", "group", "review", "overlay", "output")
MAIL_KINDS = ("data", "mapping", "template", "sequences", "mail_review", "compose", "reports")
LABELS = {"input":"PDF Input", "merge":"Merge PDFs", "extract":"Extract Regions",
          "group":"Group Mailpieces", "review":"Review", "overlay":"Overlay", "output":"Validate & Output",
          "data":"Data Input", "mapping":"Field Mapping", "template":"Letter Template",
          "sequences":"Fields & Sequences", "mail_review":"Preview & Review", "compose":"Compose",
          "reports":"Validate & Reports"}


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
        return MAIL_KINDS if self.project_kind=="mail_merge_workflow" else KINDS

    def allowed_next(self, kind):
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
        if (type(self.workflow_version) is not int or self.workflow_version not in (1,2)
                or self.project_kind not in ("pdf_workflow","mail_merge_workflow")
                or (self.project_kind=="mail_merge_workflow" and self.workflow_version!=2)
                or not isinstance(self.name,str) or len(self.name)>200 or not isinstance(self.nodes,list)
                or not 1<=len(self.nodes)<=7 or not isinstance(self.edges,list) or len(self.edges)>6):
            raise CompositionError("Unsupported workflow format or graph size.")
        ids=set()
        kinds=set()
        for n in self.nodes:
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",n.id) or n.id in ids or n.kind not in self.kinds
                    or n.kind in kinds or not isinstance(n.params,dict)
                    or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in (n.x,n.y))):
                raise CompositionError("Invalid/duplicate workflow node.")
            ids.add(n.id)
            kinds.add(n.kind)
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
        return chain

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
