import copy

import pytest

from composition.template.model import CompositionError
from workflow.branch_graph import add_route, child_spec, edge
from workflow.model import WorkflowNode, WorkflowSpec


def test_v5_default_and_legacy_roundtrip():
    for model in (WorkflowSpec.default(),WorkflowSpec.mail_merge().upgraded(4),WorkflowSpec.branched_mail_merge()):
        restored=WorkflowSpec.from_dict(model.to_dict())
        assert restored.to_dict()==model.to_dict()
    model=WorkflowSpec.branched_mail_merge()
    plan=model.execution_plan()
    assert [n.kind for n in plan.common]==["for_each","mapping","batch_sequence"]
    assert list(plan.branches)==["letters"]
    assert child_spec(plan,"letters").chain()[-1].kind=="reports"
    with pytest.raises(CompositionError,match="branched execution plan"):
        model.chain()


def test_multiple_templates_are_identified_by_branch_not_kind():
    model=add_route(WorkflowSpec.branched_mail_merge(),"Scheme G",{"conditions":[{"field":"Scheme","operator":"eq","value":"G"}]})
    plan=model.execution_plan()
    assert len(plan.branches)==2
    paths=list(plan.branches.values())
    assert paths[0][0].id!=paths[1][0].id
    assert model.execution_plan(paths[1][1].id).branches=={list(plan.branches)[1]:paths[1][:2]}


def test_common_prefix_can_be_checked_without_downstream_connections():
    model=WorkflowSpec.branched_mail_merge()
    target=model.node("batch_sequence")
    model.edges=[e for e in model.edges if e["source"]!=target.id]
    assert model.execution_plan(target.id).target is target
    with pytest.raises(CompositionError,match="Connect sources"):
        model.execution_plan()


def test_v5_rejects_cycles_nested_route_and_invalid_port():
    original=WorkflowSpec.branched_mail_merge()
    model=copy.deepcopy(original)
    model.edges.append(edge(model.node("collect").id,model.node("for_each").id))
    with pytest.raises(CompositionError):
        model.validate()
    model=copy.deepcopy(original)
    model.nodes.append(WorkflowNode("route",params=copy.deepcopy(model.node("route").params)))
    with pytest.raises(CompositionError,match="Nested"):
        model.validate()
    model=copy.deepcopy(original)
    model.edges[0]["port"]="unknown"
    with pytest.raises(CompositionError):
        model.validate()


def test_ambiguous_conditions_are_allowed_but_two_fallbacks_are_not():
    model=WorkflowSpec.branched_mail_merge()
    with pytest.raises(CompositionError,match="fallback"):
        add_route(model,"Second fallback",fallback=True)
