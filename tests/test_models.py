from pathlib import Path

from ledger.models import Project


def test_project_paths():
    p = Project(slug="trackforge", path=Path("/home/x/projects/trackforge"))
    assert p.changelog_path == Path("/home/x/projects/trackforge/docs/CHANGELOG.md")
    assert p.backlog_path == Path("/home/x/projects/trackforge/docs/BACKLOG.md")
    assert p.docs_dir == Path("/home/x/projects/trackforge/docs")
