"""Existing AcroForm values and deliberately restricted Acrobat calculations.

Descriptors contain numbers and strings only; never retain live PDF widgets.
Call apply_values inside the engine's mutation transaction.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import fitz


class FormError(ValueError):
    pass


class UnsupportedCalculation(FormError):
    pass


@dataclass(frozen=True)
class WidgetRef:
    page: int
    xref: int
    rect: tuple[float, ...]
    states: tuple[str, ...] = ()


@dataclass
class FormField:
    name: str
    kind: int
    label: str
    value: object
    flags: int
    widgets: list[WidgetRef] = field(default_factory=list)
    choices: tuple = ()
    calculation: str = ""
    scripts: tuple[str, ...] = ()
    max_length: int = 0
    signed: bool = False

    @property
    def readonly(self):
        return bool(self.flags & 1)

    @property
    def required(self):
        return bool(self.flags & 2)


def enumerate_fields(doc) -> list[FormField]:
    if doc.xref_get_key(doc.pdf_catalog(), "AcroForm/XFA")[0] != "null":
        raise FormError("XFA forms are not supported. Open an AcroForm PDF instead.")
    fields = {}
    for page in doc:
        for widget in page.widgets() or ():
            name = widget.field_name or f"Unnamed field {widget.xref}"
            states = (widget.button_states() or {}).get("normal", ())
            ref = WidgetRef(page.number, widget.xref, tuple(widget.rect), tuple(states))
            if name not in fields:
                fields[name] = FormField(
                    name, widget.field_type, widget.field_type_string,
                    widget.field_value, widget.field_flags,
                    choices=tuple(widget.choice_values or ()),
                    calculation=widget.script_calc or "",
                    scripts=tuple(key for key in ("script", "script_stroke", "script_format",
                        "script_change", "script_blur", "script_focus") if getattr(widget, key, None)),
                    max_length=widget.text_maxlen or 0, signed=bool(widget.is_signed))
            logical = fields[name]
            if widget.field_type == fitz.PDF_WIDGET_TYPE_LISTBOX and widget.field_flags & (1 << 21):
                obj = fitz.mupdf.pdf_load_object(fitz._as_pdf_document(doc), widget.xref)
                values = fitz.mupdf.pdf_dict_get_inheritable(obj, fitz.mupdf.pdf_new_name("V"))
                if fitz.mupdf.pdf_is_array(values):
                    logical.value = [fitz.mupdf.pdf_array_get_text_string(values, i)
                                     for i in range(fitz.mupdf.pdf_array_len(values))]
            if logical.kind != widget.field_type:
                raise FormError(f"Incompatible widgets share field name: {name}")
            logical.widgets.append(ref)
            logical.flags |= widget.field_flags
            if not isinstance(logical.value, list) and widget.field_value not in (None, "", "Off"):
                logical.value = widget.field_value
    return list(fields.values())


_REF = re.compile(r'''this\.getField\(\s*(["'])(.*?)\1\s*\)\.value(?:AsString)?''')
_AGG = re.compile(r'''AFSimple_Calculate\(\s*(["'])(SUM|AVG|PRD|MIN|MAX)\1\s*,\s*(.*?)\s*\)\s*;?''', re.S)


def parse_calculation(script):
    """Return (AST or aggregate, references), without executing script code."""
    script = script.strip()
    if len(script) > 8192:
        raise UnsupportedCalculation("Calculation is too complex")
    aggregate = _AGG.fullmatch(script)
    if aggregate:
        expression = aggregate[3].strip()
        if expression.startswith("new Array(") and expression.endswith(")"):
            expression = "[" + expression[10:-1] + "]"
        try:
            names = ast.literal_eval(expression)
        except (ValueError, SyntaxError) as exc:
            raise UnsupportedCalculation("Unsupported aggregate syntax") from exc
        if not isinstance(names, (list, tuple)) or not names or not all(isinstance(n, str) for n in names):
            raise UnsupportedCalculation("Expected a list of field names")
        return (aggregate[2], tuple(names)), tuple(names)
    match = re.fullmatch(r"event\.value\s*=\s*(.*?)\s*;?", script, re.S)
    if not match:
        raise UnsupportedCalculation("Unsupported calculation script")
    names = []
    def replace(match):
        names.append(match[2])
        return f"f{len(names) - 1}"
    expression = _REF.sub(replace, match[1].rstrip(";").strip())
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise UnsupportedCalculation("Unsupported formula") from exc
    nodes = list(ast.walk(tree))
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
               ast.UAdd, ast.USub, ast.Constant, ast.Name, ast.Load)
    if len(nodes) > 256 or any(not isinstance(n, allowed) for n in nodes):
        raise UnsupportedCalculation("Only field references and basic arithmetic are supported")
    for node in nodes:
        if isinstance(node, ast.Name) and node.id not in {f"f{i}" for i in range(len(names))}:
            raise UnsupportedCalculation("Unknown expression name")
        if isinstance(node, ast.Constant) and type(node.value) not in (int, float):
            raise UnsupportedCalculation("Only numeric constants are supported")
    return tree, tuple(names)


def number(value, name):
    try:
        result = Decimal(str(value).strip() or "0") if value is not None else Decimal(0)
    except InvalidOperation as exc:
        raise FormError(f"{name}: a numeric value is required") from exc
    if not result.is_finite():
        raise FormError(f"{name}: a finite numeric value is required")
    return result


def calculate(parsed, refs, values):
    nums = [number(values[name], name) for name in refs]
    if isinstance(parsed, tuple):
        op = parsed[0]
        if op == "SUM":
            return sum(nums, Decimal(0))
        if op == "AVG":
            return sum(nums, Decimal(0)) / len(nums)
        if op == "MIN":
            return min(nums)
        if op == "MAX":
            return max(nums)
        product = Decimal(1)
        for value in nums:
            product *= value
        return product
    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name):
            return nums[int(node.id[1:])]
        if isinstance(node, ast.Constant):
            return number(node.value, "Constant")
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        left, right = visit(node.left), visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise FormError("Calculation divides by zero")
        return left / right
    return visit(parsed)


def validate_values(fields, staged):
    by_name = {f.name: f for f in fields}
    values = {f.name: f.value for f in fields}
    calculations, warnings = {}, []
    blocked = set()
    for name, value in staged.items():
        if name not in by_name:
            raise FormError(f"Field no longer exists: {name}")
        item = by_name[name]
        if item.readonly or item.kind in (fitz.PDF_WIDGET_TYPE_SIGNATURE, fitz.PDF_WIDGET_TYPE_BUTTON):
            raise FormError(f"{name}: this field cannot be edited")
        if item.kind == fitz.PDF_WIDGET_TYPE_TEXT and not item.flags & (1 << 12) and "\n" in str(value):
            raise FormError(f"{name}: this is a single-line field")
        if item.max_length and len(str(value)) > item.max_length:
            raise FormError(f"{name}: exceeds {item.max_length} characters")
        options = [c[0] if isinstance(c, (tuple, list)) else c for c in item.choices]
        if item.kind in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
            options = list({s for w in item.widgets for s in w.states} | {"Off"})
        if options and not (item.kind == fitz.PDF_WIDGET_TYPE_COMBOBOX and item.flags & (1 << 18)):
            selected = value if isinstance(value, (list, tuple)) else [value]
            if any(v not in options for v in selected):
                raise FormError(f"{name}: invalid option")
        values[name] = value
    for item in fields:
        if item.scripts:
            warnings.append(f"{item.name}: validation / formatting script not executed")
        if item.calculation:
            try:
                calculations[item.name] = parse_calculation(item.calculation)
            except UnsupportedCalculation:
                blocked.add(item.name)
                warnings.append(f"{item.name}: unsupported calculation; not recalculated")
    active, done = set(), set()
    def resolve(name):
        if name in done:
            return
        if name in active:
            raise FormError(f"Circular calculation dependency: {name}")
        active.add(name)
        if name in calculations:
            parsed, refs = calculations[name]
            for ref in refs:
                if ref not in values:
                    raise FormError(f"{name}: referenced field is missing: {ref}")
                resolve(ref)
            if any(ref in blocked for ref in refs):
                blocked.add(name)
                warnings.append(f"{name}: depends on an unsupported calculation; not recalculated")
                active.remove(name)
                done.add(name)
                return
            try:
                values[name] = format(calculate(parsed, refs, values), "f")
            except (ArithmeticError, RecursionError) as exc:
                raise FormError(f"{name}: calculation failed") from exc
        active.remove(name)
        done.add(name)
    for name in calculations:
        resolve(name)
    for item in fields:
        if item.required and values[item.name] in (None, "", "Off", []):
            raise FormError(f"{item.name}: this field is required")
    return values, warnings


def _unicode_appearance(doc, ref, text):
    """Install an editable widget appearance with an embedded CJK font.

    The temporary page supplies PDF resources; its content is moved into an AP
    Form XObject before the page is removed. The AcroForm value stays editable.
    """
    rect = fitz.Rect(ref.rect)
    original_page = doc[ref.page]
    widget = original_page.load_widget(ref.xref)
    fill, border, border_width = widget.fill_color, widget.border_color, widget.border_width
    font_size, color = widget.text_fontsize, widget.text_color
    page = doc.new_page(width=rect.width, height=rect.height)
    try:
        if fill or border:
            page.draw_rect(page.rect + (0.5, 0.5, -0.5, -0.5), color=border,
                           fill=fill, width=border_width or 0)
        box = page.rect + (2, 2, -2, -2)
        writer = fitz.TextWriter(page.rect)
        font = fitz.Font("cjk")
        size = font_size or min(20, max(4, box.height * .65))
        remaining = writer.fill_textbox(box, str(text), font=font, fontsize=size, warn=False)
        while remaining and size > 4:
            size -= 1
            writer = fitz.TextWriter(page.rect)
            remaining = writer.fill_textbox(box, str(text), font=font, fontsize=size, warn=False)
        writer.write_text(page, color=color or (0, 0, 0))
        resources = doc.xref_get_key(page.xref, "Resources")[1]
        xref = doc.get_new_xref()
        doc.update_object(xref, f"<< /Type /XObject /Subtype /Form /BBox [0 0 {rect.width} {rect.height}] /Resources {resources} >>")
        doc.update_stream(xref, page.read_contents())
        doc.xref_set_key(ref.xref, "AP/N", f"{xref} 0 R")
    finally:
        doc.delete_page(doc.page_count - 1)


def apply_values(doc, staged, signatures=None, *, acknowledge_scripts=False):
    fields = enumerate_fields(doc)
    values, warnings = validate_values(fields, staged)
    if warnings and not acknowledge_scripts:
        raise FormError("Confirm unsupported scripts before applying values:\n" + "\n".join(warnings))
    appearances = []
    for item in fields:
        value = values[item.name]
        if item.kind in (fitz.PDF_WIDGET_TYPE_SIGNATURE, fitz.PDF_WIDGET_TYPE_BUTTON):
            continue
        if value == item.value and item.name not in staged:
            continue
        refs = item.widgets
        if item.kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            # Off widgets first: the selected child writes the shared parent last.
            refs = sorted(refs, key=lambda ref: value in ref.states and value != "Off")
        for ref in refs:
            page = doc[ref.page]
            widget = page.load_widget(ref.xref)
            widget.field_value = value[0] if isinstance(value, list) and value else ("" if isinstance(value, list) else value)
            if item.kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON and (value not in ref.states or value == "Off"):
                widget.field_value = False
            if item.kind == fitz.PDF_WIDGET_TYPE_TEXT:
                # PyMuPDF's setter skips empty strings; write /V explicitly so Clear
                # really clears both this widget and its logical parent.
                encoded = fitz.get_pdf_str(str(value or ""))
                doc.xref_set_key(ref.xref, "V", encoded)
                parent_type, parent = doc.xref_get_key(ref.xref, "Parent")
                if parent_type == "xref":
                    doc.xref_set_key(int(parent.split()[0]), "V", encoded)
            widget.update()
            if isinstance(value, list):
                array = "[" + " ".join(fitz.get_pdf_str(v) for v in value) + "]"
                doc.xref_set_key(ref.xref, "V", array)
                options = [c[0] if isinstance(c, (tuple, list)) else c for c in item.choices]
                indices = "[" + " ".join(str(options.index(v)) for v in value) + "]"
                doc.xref_set_key(ref.xref, "I", indices)
                parent_type, parent = doc.xref_get_key(ref.xref, "Parent")
                if parent_type == "xref":
                    doc.xref_set_key(int(parent.split()[0]), "V", array)
                labels = {c[0]: c[1] for c in item.choices if isinstance(c, (tuple, list))}
                appearances.append((ref, "\n".join(labels.get(v, v) for v in value)))
            if item.kind == fitz.PDF_WIDGET_TYPE_TEXT and any(ord(c) > 255 for c in str(value)):
                appearances.append((ref, value))
            if item.kind in (fitz.PDF_WIDGET_TYPE_LISTBOX, fitz.PDF_WIDGET_TYPE_COMBOBOX) and not isinstance(value, list):
                labels = {c[0]: c[1] for c in item.choices if isinstance(c, (tuple, list))}
                display = labels.get(value, value)
                if any(ord(c) > 255 for c in str(display)):
                    appearances.append((ref, display))
    for ref, value in appearances:
        _unicode_appearance(doc, ref, value)
    by_name = {f.name: f for f in fields}
    for name, data in (signatures or {}).items():
        item = by_name[name]
        if item.kind != fitz.PDF_WIDGET_TYPE_SIGNATURE or item.signed or item.readonly:
            raise FormError(f"{name}: signature appearance is not allowed")
        for ref in item.widgets:
            # Signature widgets can paint an opaque AP above page content.
            # Put the picture in their appearance, leaving /V absent/unchanged.
            rect = fitz.Rect(ref.rect)
            page = doc.new_page(width=rect.width, height=rect.height)
            try:
                page.insert_image(page.rect, stream=data, keep_proportion=True)
                resources = doc.xref_get_key(page.xref, "Resources")[1]
                xref = doc.get_new_xref()
                doc.update_object(xref, f"<< /Type /XObject /Subtype /Form /BBox [0 0 {rect.width} {rect.height}] /Resources {resources} >>")
                doc.update_stream(xref, page.read_contents())
                doc.xref_set_key(ref.xref, "AP/N", f"{xref} 0 R")
            finally:
                doc.delete_page(doc.page_count - 1)
    return warnings
