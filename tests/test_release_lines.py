"""Les lignes 3.0 et 3.1 évoluent sans se voler leurs numéros de tags."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "patch" / "hub-release.sh").read_text(encoding="utf-8")


def test_release_branches_are_explicit():
    assert 'main) RELEASE_LINE="3.0"' in SOURCE
    assert 'v3.1) RELEASE_LINE="3.1"' in SOURCE


def test_latest_tag_is_filtered_by_release_line():
    assert 'git tag --list "v${RELEASE_LINE}.*"' in SOURCE
    assert 'git tag --sort=-v:refname | head -1' not in SOURCE


def test_each_line_pushes_its_own_remote_branch():
    assert 'RELEASE_REMOTE_BRANCH="main"' in SOURCE
    assert 'RELEASE_REMOTE_BRANCH="v3.1"' in SOURCE
    assert 'refs/heads/$RELEASE_REMOTE_BRANCH' in SOURCE


def test_first_patch_of_new_line_is_dot_zero():
    assert 'CURRENT_TAG="v${RELEASE_LINE}.-1"' in SOURCE
