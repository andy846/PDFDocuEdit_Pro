"""Retain invalid live settings forms while navigating to other nodes."""
from __future__ import annotations

from PyQt6 import sip


def remember(window):
    getter = getattr(window, "_draft_getter", None)
    if getter is None:
        return
    try:
        dirty = getter() != window._draft_initial
    except (ValueError, TypeError):
        dirty = True
    if dirty:
        window.node_drafts[window._draft_node] = {
            "widget": window.inspector, "getter": getter, "initial": window._draft_initial,
        }


def release(window):
    old = window.inspector_scroll.takeWidget()
    if old is None:
        return
    settings = old.release_settings() if hasattr(old, "release_settings") else old
    if any(entry["widget"] is settings for entry in window.node_drafts.values()):
        settings.setParent(None)
    elif not sip.isdeleted(settings):
        settings.deleteLater()
    if old is not settings:
        old.deleteLater()


def restore(window, identity):
    entry = window.node_drafts.get(identity)
    if entry is None:
        return False
    window.inspector = entry["widget"]
    window.inspector_scroll.setWidget(window.inspector)
    window._draft_node = identity
    window._draft_getter = entry["getter"]
    window._draft_initial = entry["initial"]
    return True


def update_error(window):
    remember(window)
    window.draft_error = "Unapplied workflow settings" if window.node_drafts else ""


def flush(window, *, current_only=False):
    if window._flushing_settings:
        return True
    remember(window)
    identities = ([getattr(window, "_draft_node", "")] if current_only else list(window.node_drafts))
    for identity in identities:
        entry = window.node_drafts.get(identity)
        if entry is None:
            continue
        node = next((n for n in window.spec.nodes if n.id == identity), None)
        if node is None:
            window.node_drafts.pop(identity)
            entry["widget"].deleteLater()
            continue
        if window.active_worker or window.capture_active:
            window.message("Wait for the current task before applying settings.")
            return False
        try:
            value = entry["getter"]()
        except (ValueError, TypeError) as exc:
            window.message(f"{node.kind}: {exc}. Return to this node's Settings to repair the draft.")
            return False
        window._flushing_settings = True
        window.node_drafts.pop(identity)
        try:
            if not window.params(node, value):
                window.node_drafts[identity] = entry
                window.draft_error = "Invalid unapplied workflow settings"
                return False
        finally:
            window._flushing_settings = False
        if entry["widget"] is not window.inspector and not sip.isdeleted(entry["widget"]):
            entry["widget"].deleteLater()
    update_error(window)
    window.title()
    return True


def select(window, identity):
    if identity not in {node.id for node in window.spec.nodes}:
        return
    if not window._flushing_settings:
        # Valid drafts retain auto-apply. Invalid ones stay live during navigation.
        flush(window, current_only=True)
    release(window)
    window._draft_getter = None
    window.selected = identity
    if not restore(window, identity):
        window._build_node_settings(identity)
    update_error(window)
    window.title()
