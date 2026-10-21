from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    slug: str
    path: Path

    @property
    def docs_dir(self) -> Path:
        return self.path / "docs"

    @property
    def changelog_path(self) -> Path:
        return self.docs_dir / "CHANGELOG.md"

    @property
    def backlog_path(self) -> Path:
        return self.docs_dir / "BACKLOG.md"

    @property
    def done_path(self) -> Path:
        return self.docs_dir / "BACKLOG-DONE.md"
