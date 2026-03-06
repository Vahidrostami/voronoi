"""Tests for voronoi.server.repo_url — GitHub URL extraction."""

import pytest

from voronoi.server.repo_url import RepoRef, extract_repo_url, strip_repo_url


class TestExtractRepoUrl:
    def test_https_url(self):
        r = extract_repo_url("check https://github.com/acme/ml-model for issues")
        assert r is not None
        assert r.owner == "acme"
        assert r.name == "ml-model"

    def test_plain_github_url(self):
        r = extract_repo_url("look at github.com/acme/api")
        assert r is not None
        assert r.full_name == "acme/api"

    def test_url_with_dotgit(self):
        r = extract_repo_url("clone github.com/acme/repo.git")
        assert r is not None
        assert r.name == "repo"

    def test_no_repo_in_text(self):
        r = extract_repo_url("Why is accuracy dropping?")
        assert r is None

    def test_false_positive_and_or(self):
        r = extract_repo_url("compare this and/or that approach")
        assert r is None

    def test_false_positive_file_extension(self):
        r = extract_repo_url("look at src/main.py")
        assert r is None

    def test_clone_url_property(self):
        r = extract_repo_url("github.com/acme/ml-model")
        assert r is not None
        assert r.clone_url == "https://github.com/acme/ml-model.git"

    def test_slug_property(self):
        r = extract_repo_url("github.com/acme/ml-model")
        assert r is not None
        assert r.slug == "acme--ml-model"

    def test_url_in_question(self):
        r = extract_repo_url("Why is accuracy low in github.com/acme/ml-model?")
        assert r is not None
        assert r.full_name == "acme/ml-model"

    def test_http_url(self):
        r = extract_repo_url("http://github.com/owner/repo")
        assert r is not None
        assert r.owner == "owner"


class TestStripRepoUrl:
    def test_strips_github_url(self):
        text = strip_repo_url("Why is accuracy low in github.com/acme/ml-model?")
        assert "github.com" not in text
        assert "accuracy" in text

    def test_no_url_unchanged(self):
        text = strip_repo_url("Why is accuracy dropping?")
        assert text == "Why is accuracy dropping?"


class TestRepoRef:
    def test_frozen(self):
        r = RepoRef(owner="a", name="b")
        with pytest.raises(AttributeError):
            r.owner = "c"  # type: ignore

    def test_full_name(self):
        r = RepoRef(owner="acme", name="api")
        assert r.full_name == "acme/api"
