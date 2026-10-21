import pytest

from ledger import archive, writer
from ledger.parse import parse_backlog, parse_done

BACKLOG = """\
# Sample — Backlog

## Now

### Post-launch
- [x] **[ops]** finished thing <!-- added 2026-07-01 -->
- [ ] **[feat]** link the feedback form <!-- added 2026-06-29 -->
  URL goes in the config.
- [ ] fix the vote count display
- [ ] fix the vote count export

## Soon
- [ ] ~~old idea~~ — DONE 2026-07-02
- [ ] says SHIPPED but still open

## Someday
"""


@pytest.fixture
def proj(tmp_project):
    tmp_project.backlog_path.write_text(BACKLOG)
    return tmp_project


def test_find_open_item(proj):
    items = parse_backlog(proj.backlog_path)
    assert archive.find_open_item(items, "Feedback Form").headline == "link the feedback form"
    with pytest.raises(archive.NoMatch):
        archive.find_open_item(items, "finished thing")        # done items don't match
    with pytest.raises(archive.AmbiguousMatch) as e:
        archive.find_open_item(items, "fix the vote count")
    assert len(e.value.items) == 2
    assert archive.find_open_item(items, "fix the vote count export").headline.endswith("export")


def test_tidy_plan(proj):
    move, review = archive.tidy_plan(parse_backlog(proj.backlog_path))
    assert [i.headline for i in move] == ["finished thing", "old idea — DONE 2026-07-02"]
    assert [i.headline for i in review] == ["says SHIPPED but still open"]


def test_mark_done_moves_item_and_body(proj):
    item, _ = writer.mark_done(proj, "feedback form")
    text = proj.backlog_path.read_text()
    assert "feedback form" not in text and "URL goes in the config." not in text
    assert "\n\n\n" not in text
    done = parse_done(proj.done_path)
    assert len(done) == 1
    assert done[0].box == "x" and done[0].headline == "link the feedback form"
    assert done[0].note == "URL goes in the config."
    assert "<!-- from Now › Post-launch -->" in done[0].raw
    assert proj.done_path.read_text().startswith("# ")


def test_second_move_same_day_joins_group_newest_first(proj):
    writer.mark_done(proj, "vote count display")
    writer.mark_done(proj, "vote count export")
    text = proj.done_path.read_text()
    assert text.count("\n## ") == 1
    heads = [i.headline for i in parse_done(proj.done_path)]
    assert set(heads) == {"fix the vote count display", "fix the vote count export"}


def test_tidy_moves_done_items_and_commits(proj):
    import subprocess
    moved, review, result = writer.tidy(proj)
    assert len(moved) == 2 and len(review) == 1
    assert result.committed
    names = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=proj.path,
                           capture_output=True, text=True).stdout.split()
    assert set(names) == {"docs/BACKLOG.md", "docs/BACKLOG-DONE.md"}
    open_heads = [i.headline for i in parse_backlog(proj.backlog_path)]
    assert "finished thing" not in open_heads and "says SHIPPED but still open" in open_heads


def test_tidy_with_nothing_to_move_writes_nothing(tmp_project):
    tmp_project.backlog_path.write_text("# S — Backlog\n\n## Now\n- [ ] open\n\n## Soon\n\n## Someday\n")
    moved, review, result = writer.tidy(tmp_project)
    assert moved == [] and result is None
    assert not tmp_project.done_path.exists()


def test_blank_text_matches_no_item(proj):
    # "" is a substring of every headline, so blank text used to match them all.
    items = parse_backlog(proj.backlog_path)
    for text in ("", "   "):
        with pytest.raises(archive.NoMatch):
            archive.find_open_item(items, text)


def test_move_refuses_when_backlog_changed_since_it_was_read(proj):
    items = parse_backlog(proj.backlog_path)
    item = archive.find_open_item(items, "feedback form")
    changed = BACKLOG.replace("## Now\n", "## Now\n\nA line someone added meanwhile.\n")
    proj.backlog_path.write_text(changed)
    with pytest.raises(archive.BacklogChanged) as e:
        archive.move_items(proj, [item], "2026-09-18", mark_done=True)
    assert "run the command again" in str(e.value).lower()
    assert proj.backlog_path.read_text() == changed           # nothing cut
    assert not proj.done_path.exists()


def test_move_writes_done_list_before_backlog(proj, monkeypatch):
    """If the second write fails, the item must still exist somewhere."""
    real = archive._atomic_write

    def fail_on_backlog(path, content):
        if path == proj.backlog_path:
            raise OSError("disk full")
        real(path, content)

    monkeypatch.setattr(archive, "_atomic_write", fail_on_backlog)
    item = archive.find_open_item(parse_backlog(proj.backlog_path), "feedback form")
    with pytest.raises(OSError):
        archive.move_items(proj, [item], "2026-09-18", mark_done=True)
    assert "link the feedback form" in proj.backlog_path.read_text()
    assert proj.done_path.exists() and "link the feedback form" in proj.done_path.read_text()
