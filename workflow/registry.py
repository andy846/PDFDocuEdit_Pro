"""Declarative node capabilities. No Qt or editor dependencies."""
from dataclasses import dataclass

from composition.template.model import CompositionError

DATA_KINDS = ("clean_fields", "create_fields", "filter_records", "sort_records", "validate_data")
MEDIA_KINDS = ("media_assignment",)
PRODUCTION_KINDS = ("running_sequence", "split_output")+MEDIA_KINDS
EXTRA_KINDS = DATA_KINDS + PRODUCTION_KINDS


@dataclass(frozen=True)
class NodeDefinition:
    tool_id: str
    label: str
    inputs: tuple[str, ...]
    output: str = ""  # Empty means preserve the current result type.
    repeatable: bool = False
    description: str = ""

    def accepts(self, data_type):
        return data_type in self.inputs

    def validate_options(self, options):
        if not isinstance(options, dict):
            raise CompositionError(f"{self.label}: settings must be an object.")
        if self.tool_id=="media_assignment":
            from composition.media.model import MediaSpec
            MediaSpec.from_dict(options)
        elif self.tool_id in EXTRA_KINDS:
            from .transforms import validate_options
            validate_options(self.tool_id, options)

    def execute(self, source, target, options, **kwargs):
        from .transforms import transform
        return transform(source, target, self.tool_id, options, **kwargs)


def _definition(kind, label, inputs, output="", repeatable=False, description=""):
    return NodeDefinition(kind, label, tuple(inputs.split("|")), output, repeatable, description)


REGISTRY = {d.tool_id: d for d in (
    _definition("input", "PDF Input", "", "PDF Source"),
    _definition("merge", "Merge PDFs", "PDF Source", "PDF Source"),
    _definition("extract", "Extract Regions", "PDF Source", "Page Data"),
    _definition("group", "Group Mailpieces", "Page Data", "Mailpiece Set"),
    _definition("review", "Review", "Mailpiece Set"),
    _definition("overlay", "Overlay", "Mailpiece Set"),
    _definition("output", "Validate & Output", "Mailpiece Set", "PDF Set"),
    _definition("data", "Data Input", "", "Record Set"),
    _definition("mapping", "Field Mapping", "Record Set"),
    _definition("template", "Letter Template", "Record Set"),
    _definition("sequences", "Fields & Sequences", "Record Set"),
    _definition("mail_review", "Preview & Review", "Record Set"),
    _definition("compose", "Compose", "Record Set", "PDF Set"),
    _definition("reports", "Validate & Reports", "PDF Set", "PDF Set"),
    _definition("clean_fields", "Clean Fields", "Record Set|Page Data|Mailpiece Set", repeatable=True,
                description="Trim, join lines, remove prefixes, change case or replace literal text."),
    _definition("create_fields", "Create Fields", "Record Set|Page Data|Mailpiece Set", repeatable=True,
                description="Constants, concatenation, padding and first/last characters."),
    _definition("filter_records", "Filter Records", "Record Set|Mailpiece Set", repeatable=True,
                description="Keep matching records or complete envelopes; report every exclusion."),
    _definition("sort_records", "Sort Records", "Record Set|Mailpiece Set", repeatable=True,
                description="Stable multi-field sorting with explicit text/number types."),
    _definition("validate_data", "Validate Data", "Record Set|Page Data|Mailpiece Set", repeatable=True,
                description="Required values, lengths, numbers and unique identifiers."),
    _definition("running_sequence", "Running Sequence", "Record Set|Mailpiece Set",
                description="Generate a record/envelope or output-page sequence after selection and sorting."),
    _definition("split_output", "Split Output", "Record Set|Mailpiece Set",
                description="Partition output by a field or by whole records/envelopes."),
    _definition("media_assignment", "Media Assignment", "Record Set|Mailpiece Set",
                description="Assign logical pages to Stock, inspect physical sheets and configure PDF + PostScript or PDF + JDF output."),
)}


def default_options(kind, field="Name"):
    if kind=="media_assignment":
        from composition.media.model import default_media
        return default_media()
    return {
        "clean_fields":{"operations":[{"field":field,"operation":"trim"}]},
        "create_fields":{"fields":[{"field":"NewField","operation":"constant","value":""}]},
        "filter_records":{"mode":"all","conditions":[{"field":field,"operator":"not_empty","value":"","data_type":"text"}]},
        "sort_records":{"keys":[{"field":field,"type":"text","descending":False}]},
        "validate_data":{"checks":[{"field":field,"check":"required","severity":"error"}]},
        "running_sequence":{"name":"WorkflowSeq","start":1,"step":1,"padding":6,"prefix":"","suffix":"","scope":"record"},
        "split_output":{"method":"count","count":1000},
    }.get(kind,{})


def validate_chain(nodes, project_kind):
    state = ""
    seen = set()
    finishing = False
    for node in nodes:
        definition = REGISTRY[node.kind]
        if not definition.accepts(state):
            raise CompositionError(f"{definition.label} cannot use {state or 'an empty input'}.")
        if node.kind in ("filter_records", "sort_records") and finishing:
            raise CompositionError("Place filtering and sorting before Media Assignment / Running Sequence / Split Output.")
        if node.kind=="media_assignment" and seen.intersection(("running_sequence","split_output","overlay")):
            raise CompositionError("Place Media Assignment before Running Sequence, Split Output and Overlay.")
        if node.kind in DATA_KINDS and "media_assignment" in seen:
            raise CompositionError("Place data preparation before Media Assignment.")
        finishing = finishing or node.kind in PRODUCTION_KINDS
        if node.kind == "compose" and "template" not in seen:
            raise CompositionError("Compose needs a Letter Template step.")
        if node.kind in ("overlay", "output") and "review" not in seen:
            raise CompositionError("PDF production needs an accepted Review step.")
        state = definition.output or state
        seen.add(node.kind)
    return state
