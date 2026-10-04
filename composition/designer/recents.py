"""One cached recent-project list for every Designer project type.

Listing never stats a path (including disconnected network shares).
"""
import json
import os

from PyQt6.QtCore import QSettings


def identity(path):
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


def entries(settings=None):
    settings=settings or QSettings()
    try:
        rows=json.loads(settings.value("designer/recent_projects_v1", "[]"))
    except (ValueError, TypeError):
        rows=[]
    if not isinstance(rows,list):
        rows=[]
    rows += [{"path":p,"kind":"Template"} for p in settings.value("recent_projects",[],type=list) if isinstance(p,str)]
    unique=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("path"),str) or len(row["path"])>4096:
            continue
        key=identity(row["path"])
        if key not in seen:
            seen.add(key)
            unique.append({"path":row["path"],"kind":str(row.get("kind","Project"))[:40]})
    return unique[:20]


def remember(path, kind="Template", settings=None):
    settings=settings or QSettings()
    rows=[{"path":str(path),"kind":kind}] + [r for r in entries(settings) if identity(r["path"])!=identity(path)]
    settings.setValue("designer/recent_projects_v1",json.dumps(rows[:20]))
    settings.setValue("recent_projects",[])  # Legacy entries have now been merged.


def remove(path, settings=None):
    settings=settings or QSettings()
    rows=[r for r in entries(settings) if identity(r["path"])!=identity(path)]
    settings.setValue("designer/recent_projects_v1",json.dumps(rows))
    settings.setValue("recent_projects",[])
