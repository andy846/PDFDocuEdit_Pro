"""Shared resolution, compatibility and Windows naming boundaries."""
import pytest

from composition.production.model import ProductionJob, validate_output_name
from composition.template.model import CompositionError, parse_value, resolve_value
from core.variables import (
    VariableContext,
    VariableError,
    compile_template,
    plan_outputs,
    resolve,
    resolve_filename,
)


def context(**kwargs):
    return VariableContext.for_job(input_path="Customer File.pdf", job_id="job-1", batch_id="batch-1",
                                   sequence=125, frozen_at="2026-10-07T12:34:56+08:00", **kwargs)


def test_frozen_namespaces_and_chained_transformations():
    ctx = context(record={"Name": " 陳 大文 ", "MemberID": "000123"})
    assert resolve('{{input.stem|replace:" ":"_"}}_{{workflow.sequence|pad:6}}.pdf', ctx).value == "Customer_File_000125.pdf"
    assert resolve('{{record.Name|trim}} {{record.MemberID}} {{system.date|date:"%Y%m%d"}}', ctx).value == "陳 大文 000123 20261007"
    assert resolve("{{Date}} {{Time}} {{JobID}}", ctx).value == "2026-10-07 12-34-56 job-1"
    assert resolve("{{JobID}}", VariableContext(**ctx.to_dict())).value == "job-1"


def test_legacy_data_has_precedence_and_missing_designer_fields_stay_strict():
    tokens = parse_value("ID: {{WorkflowSeq}}")
    assert resolve_value(tokens, {"WorkflowSeq": "0099"}) == "ID: 0099"
    assert resolve("{{WorkflowSeq}}", context(record={"WorkflowSeq": "client"})).value == "client"
    with pytest.raises(CompositionError, match="Missing field: WorkflowSeq"):
        resolve_value(tokens, {})
    with pytest.raises(CompositionError):
        parse_value("{{record.Name|upper}}")


def test_missing_default_empty_zero_and_preview():
    ctx = context(record={"Empty": "", "Zero": 0})
    assert resolve('{{record.Missing|default:"UNKNOWN"}}/{{record.Empty|default:"x"}}/{{record.Zero|default:"x"}}', ctx).value == "UNKNOWN/x/0"
    with pytest.raises(VariableError, match="Missing field: record.Missing"):
        resolve("{{record.Missing}}", ctx)
    preview = resolve("{{record.Missing}}", ctx, "preview")
    assert preview.issues and "Missing" in preview.value


@pytest.mark.parametrize("value", ["{{", "}}", "{{}}", "{{os.system}}", "{{record.x[0]}}",
                                      "{{record.x|eval}}", "{{record.x|pad:0}}",
                                      '{{record.x|replace:"":"x"}}', '{{record.x|default:"open}}'])
def test_bad_syntax_and_executable_tokens_are_rejected(value):
    with pytest.raises(VariableError):
        compile_template(value)


def test_quoted_separators_and_escape():
    assert resolve('{{record.x|replace:"|":"_"}}', context(record={"x": "a|b"})).value == "a_b"
    assert resolve('{{record.x|replace:":":"_"}}', context(record={"x": "a:b"})).value == "a_b"
    assert resolve('{{record.x|default:"a\\\"b"}}', context()).value == 'a"b'
    assert resolve('{{record.x|default:"end}}text"}}', context()).value == 'end}}text'
    assert resolve('{{system.date|date:"%% %Y"}}', context()).value == '% 2026'
    with pytest.raises(VariableError, match="1,024"):
        compile_template("{{WorkflowSeq}}" * 1025)


def test_formatting_never_truncates_overflow_or_runs_code():
    with pytest.raises(VariableError, match="not truncated"):
        resolve("{{workflow.sequence|pad:2}}", context())
    with pytest.raises(VariableError, match="ASCII integer"):
        resolve("{{record.x|pad:6}}", context(record={"x": "１２"}))
    value = '__import__("os").system("bad")'
    assert resolve("{{record.x}}", context(record={"x": value})).value == value


def test_filename_sanitisation_only_changes_output_and_is_deterministic():
    ctx = context(record={"Name": "CON", "Other": "陳/大文:有限公司"})
    assert resolve_filename("{{record.Name}}.pdf", ctx).value == "_CON.pdf"
    result = resolve_filename("{{record.Other}}.pdf", ctx)
    assert result.value == "陳_大文_有限公司.pdf" and result.issues
    assert ctx.namespaces["record"]["Other"] == "陳/大文:有限公司"
    long = context(record={"Name": "😀" * 200})
    result = resolve_filename("{{record.Name}}.pdf", long)
    assert len(result.value.encode("utf-16-le")) // 2 <= 160
    assert result == resolve_filename("{{record.Name}}.pdf", long)


def test_collision_existing_source_and_empty_outputs(tmp_path):
    with pytest.raises(VariableError, match="Duplicate"):
        plan_outputs([context(record={"Name": "a:b"}), context(record={"Name": "a?b"})],
                     "{{record.Name}}.pdf", tmp_path)
    source = tmp_path / "Customer File.pdf"
    source.touch()
    with pytest.raises(VariableError, match="replace its source"):
        plan_outputs([context()], "{{input.filename}}", tmp_path, sources=[source])
    with pytest.raises(VariableError, match="already exists"):
        plan_outputs([context()], "{{input.filename}}", tmp_path)
    with pytest.raises(VariableError):
        resolve_filename("{{record.Blank}}", context(record={"Blank": ""}))


@pytest.mark.parametrize("name", ["CON.pdf", "LPT1.pdf", "a/b.pdf", ".pdf", "..pdf", "name.pdf."])
def test_static_production_names_remain_strict(name):
    with pytest.raises(CompositionError):
        validate_output_name(name)


def test_production_name_uses_prepared_context_without_changing_template():
    job = ProductionJob(template={"name": "Letter"}, record_store="", output_dir="unused",
                        output_name="{{JobID}}_{{system.date}}.pdf", job_id="stable",
                        variable_context=context().to_dict())
    assert job.resolved_output_name() == "job-1_2026-10-07.pdf"
    assert "{{JobID}}" in job.output_name
