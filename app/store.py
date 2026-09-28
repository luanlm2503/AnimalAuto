"""Project storage on disk."""
import json
import re
import secrets
import unicodedata
from pathlib import Path

from .models import Project

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
OUTPUT = ROOT / "output"


def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", pid):
        raise ValueError(f"bad project id: {pid!r}")
    return PROJECTS / pid


def slug(text: str, fallback: str = "item") -> str:
    """ASCII id/file name; Vietnamese diacritics are dropped ("chuột xám" -> "chuot_xam")."""
    t = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return s[:40] or fallback


def new_id(name: str) -> str:
    return f"{slug(name, 'project')}_{secrets.token_hex(3)}"


def list_projects() -> list[dict]:
    out = []
    for f in sorted(PROJECTS.glob("*/project.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": data["id"], "name": data["name"]})
        except (OSError, ValueError, KeyError):
            continue
    return out


def load_project(pid: str) -> Project:
    f = project_dir(pid) / "project.json"
    return Project.model_validate_json(f.read_text(encoding="utf-8"))


def save_project(p: Project) -> Project:
    d = project_dir(p.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "project.json.tmp"
    tmp.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(d / "project.json")
    return p


def create_project(name: str) -> Project:
    p = Project(id=new_id(name), name=name or "Project")
    for sub in ("assets", "animals", "sounds", "src"):
        (project_dir(p.id) / sub).mkdir(parents=True, exist_ok=True)
    return save_project(p)
