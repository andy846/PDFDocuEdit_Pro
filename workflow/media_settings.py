"""One headless resolution contract for inherited and explicit workflow media."""
from copy import deepcopy
from dataclasses import dataclass

from composition.media.model import MediaSpec
from composition.template.model import CompositionError


@dataclass(frozen=True)
class MediaResolution:
    media: dict
    source: str


def settings_source(options=None):
    if options is None:
        return "project"
    if not isinstance(options, dict):
        raise CompositionError("Media settings must be an object.")
    source = options.get("settings_source", "workflow")
    if source not in ("project", "workflow"):
        raise CompositionError("Select Project settings or Workflow override for print media.")
    return source


def media_options(options):
    settings_source(options)
    value = deepcopy({k: v for k, v in options.items() if k != "settings_source"})
    MediaSpec.from_dict(value)
    return value


def resolve_media_settings(project_media, options=None):
    source = settings_source(options)
    draft = media_options(options) if options is not None else {}
    value = deepcopy(project_media or {}) if source == "project" else draft
    MediaSpec.from_dict(value)
    return MediaResolution(value, source)


def requires_project_media(options):
    # Legacy disabled-media Overlay jobs retain project duplex. Explicit
    # overrides and enabled legacy media have no downstream project dependency.
    return settings_source(options)=="project" or (
        "settings_source" not in options and not options.get("enabled"))


def pdf_media_settings(spec):
    """Resolve only declared media dependencies, without reading unrelated drafts."""
    from composition.overlay.serializer import load_project
    node=spec.node("media_assignment")
    options=node.params if node else None
    needed=options is None or requires_project_media(options)
    overlay=getattr(spec,"spec",spec).node("overlay")
    project=load_project(overlay.params["path"]) if needed and overlay and overlay.params.get("path") else None
    result=resolve_media_settings(project.media if project else {},options)
    duplex=result.media.get("duplex",False) if result.media.get("enabled") or (node and options.get("settings_source")=="workflow") else (
        project.settings.duplex if project else result.media.get("duplex",False))
    return result,duplex


def media_summary(options):
    source = settings_source(options)
    if source == "project":
        return "Project settings · printing, Stock and printer profile"
    media = media_options(options)
    printing = "Duplex" if media.get("duplex") else "Simplex"
    if not media.get("enabled"):
        return f"Workflow override · {printing} · PDF only (media off)"
    profile = media.get("printer_profile", {})
    backend = "PDF + PostScript" if profile.get("backend") == "postscript" else "PDF + JDF"
    return f"Workflow override · {printing} · {backend} · {len(media.get('stocks', []))} Stocks · {profile.get('profile_name') or 'Unnamed profile'}"
