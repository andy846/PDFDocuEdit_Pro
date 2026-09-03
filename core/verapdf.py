"""Offline veraPDF CLI discovery and report normalisation."""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .analysis import (
    Finding,
    FindingSource,
    Severity,
    ValidationStatus,
    ValidationSummary,
)
from .platform_service import PlatformService
from .resources import bundle_root

SUPPORTED_PROFILES: tuple[tuple[str, str], ...] = (
    ("1a", "PDF/A-1a"),
    ("1b", "PDF/A-1b"),
    ("2a", "PDF/A-2a"),
    ("2b", "PDF/A-2b"),
    ("2u", "PDF/A-2u"),
    ("3a", "PDF/A-3a"),
    ("3b", "PDF/A-3b"),
    ("3u", "PDF/A-3u"),
    ("4", "PDF/A-4"),
    ("4e", "PDF/A-4e"),
    ("4f", "PDF/A-4f"),
    ("ua1", "PDF/UA-1 (machine checks)"),
    ("ua2", "PDF/UA-2 (machine checks)"),
)


@dataclass(frozen=True)
class VeraPdfRuntime:
    launcher: str
    backend: str
    home: str
    java_home: str = ""


@dataclass(frozen=True)
class VeraPdfResult:
    profile: str
    compliant: bool | None
    findings: tuple[Finding, ...]
    raw_xml: str
    message: str = ""
    summary: ValidationSummary | None = None


def _runnable(path: Path) -> bool:
    return path.is_file() and (
        platform.system() == "Windows" or os.access(path, os.X_OK)
    )


def find_verapdf_runtime(configured_path: str | None = None) -> VeraPdfRuntime | None:
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    roots = [bundle_root() / "verapdf", bundle_root() / "VeraPDF"]
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent / "verapdf")
    names = (
        "verapdf.bat",
        "verapdf",
        "bin/verapdf.bat",
        "bin/verapdf",
    )
    for root in roots:
        candidates.extend(root / name for name in names)
    system = shutil.which("verapdf.bat") or shutil.which("verapdf")
    if system:
        candidates.append(Path(system))
    for candidate in candidates:
        if candidate.is_dir():
            nested = candidate / (
                "verapdf.bat" if platform.system() == "Windows" else "verapdf"
            )
            if _runnable(nested):
                candidate = nested
        if _runnable(candidate):
            resolved = candidate.resolve()
            bundled = bundle_root() in resolved.parents
            home = (
                resolved.parent.parent
                if resolved.parent.name.casefold() == "bin"
                else resolved.parent
            )
            java_home = ""
            java_name = "java.exe" if platform.system() == "Windows" else "java"
            for runtime_dir in (home / "jre", home / "runtime", home / "java"):
                if (runtime_dir / "bin" / java_name).is_file():
                    java_home = str(runtime_dir)
                    break
            return VeraPdfRuntime(
                str(resolved),
                "Bundled veraPDF" if bundled else "External veraPDF",
                str(home),
                java_home,
            )
    return None


def command_for(runtime: VeraPdfRuntime, arguments: list[str]) -> list[str]:
    launcher = Path(runtime.launcher)
    java_name = "java.exe" if platform.system() == "Windows" else "java"
    java = Path(runtime.java_home) / "bin" / java_name if runtime.java_home else None
    jars = sorted((Path(runtime.home) / "bin").glob("cli-*.jar"))
    if java is not None and java.is_file() and len(jars) == 1:
        return [str(java), "-jar", str(jars[0]), *arguments]
    if launcher.suffix.casefold() in {".bat", ".cmd"}:
        return ["cmd.exe", "/d", "/s", "/c", "call", str(launcher), *arguments]
    return [str(launcher), *arguments]


def _result_without_validation(
    profile: str,
    message: str,
    status: ValidationStatus,
) -> VeraPdfResult:
    standard = dict(SUPPORTED_PROFILES).get(profile, profile)
    return VeraPdfResult(
        profile,
        None,
        (),
        "",
        message,
        ValidationSummary(
            standard=standard,
            profile=profile,
            compliant=None,
            message=message,
            status=status,
        ),
    )


def _java_available(runtime: VeraPdfRuntime) -> bool:
    java_name = "java.exe" if platform.system() == "Windows" else "java"
    if runtime.java_home:
        return (Path(runtime.java_home) / "bin" / java_name).is_file()
    return shutil.which("java") is not None


def _execution_failure(stderr: str, returncode: int) -> str:
    text = stderr.casefold()
    if "java" in text and any(
        token in text
        for token in ("not found", "not recognized", "could not find", "no such file")
    ):
        return "Java runtime was not found."
    if returncode:
        return f"veraPDF exited with status code {returncode}."
    return "veraPDF could not be started."


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.casefold() for name in names}
    return next(
        (
            (child.text or "").strip()
            for child in element.iter()
            if _local_name(child.tag) in wanted and (child.text or "").strip()
        ),
        "",
    )


def _pages_from_text(value: str) -> set[int]:
    pages: set[int] = set()
    for match in re.finditer(r"page(?:number)?\s*[:=]\s*(\d+)", value, re.I):
        pages.add(max(0, int(match.group(1)) - 1))
    # veraPDF object contexts use zero-based array indexes: /pages[0](2 0 obj PDPage).
    for match in re.finditer(r"/pages?\[(\d+)\]", value, re.I):
        pages.add(int(match.group(1)))
    return pages


def _pages_from_element(element: ET.Element) -> tuple[int, ...]:
    values = [element.text or "", *element.attrib.values()]
    for child in element.iter():
        values.extend([child.text or "", *child.attrib.values()])
    return tuple(
        sorted({page for value in values for page in _pages_from_text(str(value))})
    )


def _page_from_element(element: ET.Element) -> int | None:
    pages = _pages_from_element(element)
    return pages[0] if len(pages) == 1 else None


def _rule_category(text: str) -> str:
    value = text.casefold()
    if any(token in value for token in ("font", "fontdescriptor", "embedded")):
        return "Fonts"
    if any(
        token in value
        for token in (
            "devicergb",
            "devicecmyk",
            "icc",
            "outputintent",
            "colour",
            "color space",
            "defaultrgb",
            "defaultcmyk",
        )
    ):
        return "Color"
    if any(token in value for token in ("metadata", "xmp", "info dictionary")):
        return "Metadata"
    if "transparen" in value:
        return "Transparency"
    if "annot" in value:
        return "Annotation"
    if any(token in value for token in ("encrypt", "security", "permission")):
        return "Security"
    if any(
        token in value
        for token in (
            "header",
            "pdf version",
            "trailer",
            "catalog",
            "file identifier",
            "structure",
        )
    ):
        return "Structure"
    return "PDF/A Compliance"


def _friendly_summary(text: str, category: str, clause: str, test_number: str) -> str:
    value = text.casefold()
    if "devicergb" in value:
        return "DeviceRGB used without a valid RGB colour profile"
    if "devicecmyk" in value:
        return "DeviceCMYK used without a valid CMYK colour profile"
    if "not embedded" in value or ("font" in value and "embedded" in value):
        return "Font program is not embedded"
    if "metadata" in value and any(
        token in value
        for token in ("missing", "shall contain", "not present", "invalid")
    ):
        return "Required XMP metadata is missing or invalid"
    if "info dictionary" in value:
        return "Document information dictionary is not PDF/A compliant"
    if "header" in value or "pdf version" in value:
        return "PDF header/version does not match the selected PDF/A profile"
    if "file identifier" in value or (category == "Structure" and "trailer" in value):
        return "Document trailer file identifier is missing or invalid"
    suffix = ".".join(part for part in (clause, test_number) if part)
    return (
        f"PDF/A conformance rule {suffix} failed"
        if suffix
        else "PDF/A conformance rule failed"
    )


def _failed(element: ET.Element) -> bool:
    attributes = {
        str(key).casefold(): str(value).casefold()
        for key, value in element.attrib.items()
    }
    return (
        attributes.get("status", "") in {"failed", "fail", "false"}
        or attributes.get("passed", "") == "false"
    )


def parse_verapdf_xml(xml_text: str, profile: str) -> VeraPdfResult:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        standard = dict(SUPPORTED_PROFILES).get(profile, profile)
        message = "veraPDF returned an unreadable validation report."
        return VeraPdfResult(
            profile,
            None,
            (),
            xml_text,
            message,
            ValidationSummary(
                standard=standard,
                profile=profile,
                compliant=None,
                message=message,
                status=ValidationStatus.ERROR,
            ),
        )

    compliant: bool | None = None
    for element in root.iter():
        attributes = {
            str(key).casefold(): str(value) for key, value in element.attrib.items()
        }
        statement = attributes.get("iscompliant")
        if statement is not None:
            compliant = statement.casefold() == "true"

    failed_rules: dict[tuple[str, str, str], ET.Element] = {}
    passed_rules: set[tuple[str, str, str]] = set()
    for element in root.iter():
        if _local_name(element.tag) != "rule":
            continue
        attributes = {
            str(key).casefold(): str(value) for key, value in element.attrib.items()
        }
        identity = (
            attributes.get("specification", ""),
            attributes.get("clause", ""),
            attributes.get("testnumber", ""),
        )
        if _failed(element):
            failed_rules.setdefault(identity, element)
        else:
            status = attributes.get("status", "").casefold()
            passed = attributes.get("passed", "").casefold()
            if status in {"passed", "pass", "true"} or passed == "true":
                passed_rules.add(identity)

    findings: list[Finding] = []
    failed_check_count = 0
    for identity, rule in failed_rules.items():
        attributes = {
            str(key).casefold(): str(value) for key, value in rule.attrib.items()
        }
        specification, clause, test_number = identity
        checks = [
            child
            for child in rule.iter()
            if _local_name(child.tag) == "check" and _failed(child)
        ]
        try:
            check_count = int(attributes.get("failedchecks", "") or len(checks) or 1)
        except ValueError:
            check_count = len(checks) or 1
        failed_check_count += check_count

        description = (
            attributes.get("description")
            or attributes.get("message")
            or _child_text(rule, "description")
            or "veraPDF conformance rule failed"
        )
        error_messages = []
        contexts = []
        pages = set(_pages_from_element(rule))
        object_refs: list[str] = []
        for check in checks:
            error = _child_text(check, "errormessage", "error", "message")
            context = _child_text(check, "context")
            if error and error not in error_messages:
                error_messages.append(error)
            if context and context not in contexts:
                contexts.append(context)
            pages.update(_pages_from_element(check))
            for candidate in (context, error):
                for match in re.findall(r"\b\d+\s+\d+\s+obj\b", candidate, re.I):
                    if match not in object_refs:
                        object_refs.append(match)

        combined = " ".join(
            value
            for value in (
                specification,
                clause,
                description,
                _child_text(rule, "object", "test"),
                *error_messages[:3],
            )
            if value
        )
        category = _rule_category(combined)
        summary = _friendly_summary(combined, category, clause, test_number)
        detail_parts = [description]
        if error_messages and error_messages[0] != description:
            detail_parts.append(error_messages[0])
        detail_parts.append(
            f"{check_count} failed object check{'s' if check_count != 1 else ''}"
        )
        if pages:
            page_preview = ", ".join(str(page + 1) for page in sorted(pages)[:20])
            if len(pages) > 20:
                page_preview += ", …"
            detail_parts.append(f"Affected pages: {page_preview}")
        if object_refs:
            object_preview = ", ".join(object_refs[:10])
            if len(object_refs) > 10:
                object_preview += ", …"
            detail_parts.append(f"Objects: {object_preview}")
        rule_suffix = ".".join(part for part in (clause, test_number) if part)
        stable_id = rule_suffix or specification or "rule"
        sorted_pages = tuple(sorted(pages))
        findings.append(
            Finding(
                source=FindingSource.STANDARD,
                rule_id=f"verapdf.{stable_id}",
                severity=Severity.ERROR,
                page=sorted_pages[0] if len(sorted_pages) == 1 else None,
                summary=summary,
                details=" · ".join(detail_parts)[:4000],
                value=rule_suffix or specification,
                category=category,
                pages=sorted_pages,
                object_ref=object_refs[0] if object_refs else "",
                raw_data={
                    "specification": specification,
                    "clause": clause,
                    "test_number": test_number,
                    "failed_checks": check_count,
                },
            )
        )

    # Some report formats only provide an aggregate compliance result.
    if compliant is False and not findings:
        findings.append(
            Finding(
                FindingSource.STANDARD,
                "verapdf.non_compliant",
                Severity.ERROR,
                None,
                "Document is not compliant with the selected profile",
                profile,
                category="PDF/A Compliance",
            )
        )

    standard = dict(SUPPORTED_PROFILES).get(profile, profile)
    summary = ValidationSummary(
        standard=standard,
        profile=profile,
        compliant=compliant,
        failed_rule_count=len(failed_rules),
        passed_rule_count=len(passed_rules),
        failed_check_count=failed_check_count,
        status=(
            ValidationStatus.PASS
            if compliant is True
            else ValidationStatus.FAIL
            if compliant is False
            else ValidationStatus.ERROR
        ),
    )
    return VeraPdfResult(profile, compliant, tuple(findings), xml_text, summary=summary)


def validate_with_verapdf(
    source_path: str | Path,
    profile: str,
    *,
    configured_path: str | None = None,
    is_cancelled=None,
) -> VeraPdfResult:
    runtime = find_verapdf_runtime(configured_path)
    if runtime is None:
        return _result_without_validation(
            profile,
            "veraPDF executable was not found.",
            ValidationStatus.VALIDATOR_UNAVAILABLE,
        )
    if not _java_available(runtime):
        return _result_without_validation(
            profile,
            "Java runtime was not found.",
            ValidationStatus.VALIDATOR_UNAVAILABLE,
        )
    arguments = [
        "--format",
        "xml",
        "--flavour",
        profile,
        str(Path(source_path).resolve()),
    ]
    environment = os.environ.copy()
    if runtime.java_home:
        environment["JAVA_HOME"] = runtime.java_home
        environment["PATH"] = (
            str(Path(runtime.java_home) / "bin")
            + os.pathsep
            + environment.get("PATH", "")
        )
    try:
        result = PlatformService.run_cancellable(
            command_for(runtime, arguments),
            is_cancelled=is_cancelled,
            timeout=900,
            cwd=runtime.home,
            env=environment,
        )
    except FileNotFoundError:
        return _result_without_validation(
            profile,
            "veraPDF executable was not found.",
            ValidationStatus.VALIDATOR_UNAVAILABLE,
        )
    except TimeoutError:
        return _result_without_validation(
            profile,
            "veraPDF validation timed out.",
            ValidationStatus.ERROR,
        )
    except OSError:
        return _result_without_validation(
            profile,
            "veraPDF could not be started.",
            ValidationStatus.VALIDATOR_UNAVAILABLE,
        )
    payload = result.stdout.strip()
    if not payload:
        return _result_without_validation(
            profile,
            _execution_failure(result.stderr, result.returncode),
            ValidationStatus.ERROR,
        )
    parsed = parse_verapdf_xml(payload, profile)
    if parsed.message:
        return parsed
    return VeraPdfResult(
        parsed.profile,
        parsed.compliant,
        parsed.findings,
        parsed.raw_xml,
        "",
        parsed.summary,
    )


__all__ = [
    "SUPPORTED_PROFILES",
    "VeraPdfResult",
    "VeraPdfRuntime",
    "command_for",
    "find_verapdf_runtime",
    "parse_verapdf_xml",
    "validate_with_verapdf",
]
