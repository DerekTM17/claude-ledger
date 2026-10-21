"""FastAPI app: read-only views over project files."""
from __future__ import annotations

import hashlib
import os
from datetime import date as _date, datetime as _datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from ledger import markdown as _md  # for SubsectionNotFoundError / MarkdownStructureError
from ledger.markdown import render_text
from ledger import views
from ledger import writer as _writer
from ledger.rules import TAG_MAX_CHARS, RuleViolation

from ledger.config import default_config_path, load_config
from ledger.discovery import default_projects_root, discover_projects
from ledger.git import recent_commits
from ledger.memory import memory_path_for, read_description

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

app = FastAPI(title="ledger")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# path -> (mtime, hash) cache, so a static file is hashed once per change,
# not on every request.
_static_version_cache: dict[Path, tuple[float, str]] = {}


def _static_version(file_path: Path) -> str:
    """Short content hash for a static file, recomputed only when its mtime changes.

    Returns "" if the file is missing, so a dropped stylesheet doesn't 500 the page.
    """
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return ""
    cached = _static_version_cache.get(file_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()[:8]
    _static_version_cache[file_path] = (mtime, digest)
    return digest


def static_url(request: Request, path: str) -> str:
    """Absolute URL for a static file, with a `?v=` tag derived from its contents.

    A changed file gets a new URL, so browsers don't serve it from a stale cache.
    """
    url = str(request.url_for("static", path=path))
    version = _static_version(STATIC_DIR / path)
    return f"{url}?v={version}" if version else url


templates.env.globals["static_url"] = static_url


def _projects_root() -> Path:
    return Path(os.environ.get("LEDGER_PROJECTS_ROOT") or default_projects_root())


def _no_memory() -> bool:
    return os.environ.get("LEDGER_NO_MEMORY") == "1"


def _writes_enabled() -> bool:
    return os.environ.get("LEDGER_ALLOW_WRITES") == "1"


def _load_projects():
    cfg = load_config(default_config_path())
    return discover_projects(projects_root=_projects_root(), config=cfg), cfg


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    projects, _cfg = _load_projects()
    today = _date.today()
    data = views.dashboard(projects, today)
    generated = _datetime.now()
    return templates.TemplateResponse(
        request, "dashboard.html", {
            **data,
            "generated_iso": generated.isoformat(timespec="seconds"),
            "generated_label": generated.strftime("%H:%M"),
        }
    )


def _project_page(request: Request, p, status_code: int = 200, form: dict | None = None,
                  errors: dict | None = None):
    cfg = load_config(default_config_path())
    memory_text, memory_file = "", None
    if not _no_memory():
        memory_file = memory_path_for(p.slug, override=cfg.memory_overrides.get(p.slug))
        memory_text = read_description(memory_file) or ""
    # The description is markdown (bold, `code`); render it like a note.
    ctx = {**views.project(p, _date.today()), "memory_html": Markup(render_text(memory_text)),
           "memory_file": str(memory_file) if memory_file else "",
           "git": recent_commits(p.path, limit=10), "writes_enabled": _writes_enabled(),
           "form": form or {}, "errors": errors or {}, "tag_max": TAG_MAX_CHARS}
    return templates.TemplateResponse(request, "project.html", ctx, status_code=status_code)


@app.get("/p/{slug}", response_class=HTMLResponse)
def project_view(slug: str, request: Request):
    p = _resolve_project_or_404(slug)
    return _project_page(request, p)


@app.get("/search", response_class=HTMLResponse)
def search_view(request: Request, q: str | None = None):
    q = (q or "").strip()
    case_sensitive = q.startswith('"') and q.endswith('"') and len(q) >= 2
    needle = q[1:-1] if case_sensitive else q
    if not needle.strip():
        # An empty box (or just "") is no query: show the page's own hint,
        # not an error.
        return templates.TemplateResponse(
            request, "search.html", {
                "q": "", "groups": [], "empty_state": True,
            }
        )
    projects, _ = _load_projects()
    groups = views.search(projects, needle, case_sensitive, _date.today())
    return templates.TemplateResponse(
        request, "search.html", {
            "q": q, "groups": groups, "empty_state": False,
        }
    )


def _check_same_origin(request: Request) -> None:
    """403 if Origin or Referer points to a different host than the request.

    Parses the Origin/Referer URL and compares netloc exactly — a substring
    check would let `evil-localhost:7777.attacker.com` pass when host is
    `localhost:7777`.
    """
    from urllib.parse import urlparse
    host = request.headers.get("host", "")
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin is None:
        return  # missing Origin/Referer = same-origin form post; allow
    origin_host = urlparse(origin).netloc
    if origin_host and host and origin_host != host:
        raise HTTPException(status_code=403, detail="cross-origin POST refused")


def _resolve_project_or_404(slug: str):
    projects, _ = _load_projects()
    for p in projects:
        if p.slug == slug:
            return p
    raise HTTPException(status_code=404, detail=f"unknown project: {slug}")


@app.post("/p/{slug}/backlog")
def post_backlog(slug: str, request: Request,
                 text: str | None = Form(default=None), horizon: str = Form("Soon"),
                 tag: str | None = Form(None), note: str | None = Form(None)):
    if not _writes_enabled():
        raise HTTPException(status_code=403, detail="writes disabled")
    _check_same_origin(request)
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    if horizon not in ("Now", "Soon", "Someday"):
        raise HTTPException(status_code=400, detail="invalid horizon")
    project = _resolve_project_or_404(slug)
    try:
        _writer.add_backlog_item(project, text=text.strip(), horizon=horizon,
                                 tag=(tag.strip() if tag else None),
                                 note=(note.strip() or None) if note else None)
    except RuleViolation as e:
        return _project_page(request, project, 400,
                             form={"text": text or "", "note": note or "",
                                   "horizon": horizon, "tag": tag or ""},
                             errors={"backlog": [x.message for x in e.problems]})
    except _md.SubsectionNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"sub-section not found: {e}")
    except _md.MarkdownStructureError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/p/{slug}", status_code=303)


@app.post("/p/{slug}/changelog")
def post_changelog(slug: str, request: Request,
                   title: str | None = Form(default=None),
                   why: str | None = Form(None)):
    if not _writes_enabled():
        raise HTTPException(status_code=403, detail="writes disabled")
    _check_same_origin(request)
    if not title or not title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    project = _resolve_project_or_404(slug)
    try:
        _writer.add_changelog_entry(project, title=title.strip(),
                                    why=(why.strip() if why else None))
    except RuleViolation as e:
        return _project_page(request, project, 400,
                             form={"title": title or "", "why": why or ""},
                             errors={"changelog": [x.message for x in e.problems]})
    return RedirectResponse(url=f"/p/{slug}", status_code=303)
