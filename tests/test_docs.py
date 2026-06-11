"""Phase 5 (6.5) tests: docs fetch + cache correctness (C18, C19, C20).

All tests are fully offline — monkeypatched urlopen, no real network.

Coverage:
  C18 — _version_tag() omits .0 patch when version_patch == 0.
  C19 — cache lives under godot_docs/<tag>/<ClassName>.xml; atomic write;
         malformed XML leaves no file behind; different-tag call does not read
         the first tag's cache.
  C20 — connection error (non-404) sets the network-down latch; subsequent call
         for a different class does NOT attempt a fetch (urlopen called once).
         A 404 HTTPError does NOT trip the latch.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from godot_mcp import config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extension_api(tmp_path: Path, major: int, minor: int, patch: int) -> Path:
    """Write a minimal extension_api.json to tmp_path and return its path."""
    dest = tmp_path / "extension_api.json"
    dest.write_text(
        json.dumps({
            "header": {
                "version_major": major,
                "version_minor": minor,
                "version_patch": patch,
                "version_status": "stable",
            }
        }),
        encoding="utf-8",
    )
    return dest


def _minimal_xml(cls_name: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<class name="{cls_name}">\n'
        f'  <brief_description>Brief desc for {cls_name}.</brief_description>\n'
        f'  <description>Full desc.</description>\n'
        f'</class>\n'
    )


def _fake_urlopen_ok(xml: str):
    """Return a fake urlopen that succeeds with the given XML bytes."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(return_value=xml.encode("utf-8"))
    return MagicMock(return_value=cm)


def _fake_urlopen_connection_error():
    """Return a fake urlopen that raises a non-HTTP connection error."""
    def _raise(*args, **kwargs):
        raise socket.error("Connection refused")
    return _raise


def _fake_urlopen_url_error_not_404():
    """Return a fake urlopen that raises URLError with a non-HTTP reason."""
    def _raise(*args, **kwargs):
        raise urllib.error.URLError(reason="Network is unreachable")
    return _raise


def _fake_urlopen_404():
    """Return a fake urlopen that raises an HTTP 404 error."""
    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="http://example.com",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
    return _raise


def _fake_urlopen_malformed_xml():
    """Return a fake urlopen returning bytes that are not valid XML."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(return_value=b"<NOT VALID XML <<<")
    return MagicMock(return_value=cm)


# ---------------------------------------------------------------------------
# Reset docs module state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_docs_state(monkeypatch, tmp_path):
    """Reset all module-level state in docs.py before each test.

    Monkeypatches:
    - config.DATA_DIR → a fresh tmp_path sub-dir (no real data dir used)
    - config.EXTENSION_API → a sentinel path (tests that need it override it)
    - docs._tag → None (forces re-read of extension_api.json)
    - docs._mem → {} (no cached results)
    - docs._network_down → False (no pre-existing latch)
    - docs._CACHE → recalculated from the patched DATA_DIR
    """
    import godot_mcp.docs as docs_mod

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "EXTENSION_API", data_dir / "extension_api.json")
    monkeypatch.setattr(docs_mod, "_tag", None)
    monkeypatch.setattr(docs_mod, "_mem", {})
    monkeypatch.setattr(docs_mod, "_network_down", False)
    # Recalculate _CACHE to point at the tmp data dir
    monkeypatch.setattr(docs_mod, "_CACHE", data_dir / "godot_docs")
    yield


# ---------------------------------------------------------------------------
# C18 — _version_tag() .0 patch omission
# ---------------------------------------------------------------------------

class TestVersionTag:
    """C18: version_patch == 0 → X.Y-stable; non-zero → X.Y.Z-stable."""

    def test_patch_zero_emits_no_dot_zero(self, tmp_path, monkeypatch):
        """version_patch=0 must produce '4.2-stable', not '4.2.0-stable'."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)
        tag = docs_mod._version_tag()
        assert tag == "4.2-stable", f"Expected '4.2-stable', got {tag!r}"
        assert ".0" not in tag, f"Patch 0 must not appear in tag: {tag!r}"

    def test_patch_nonzero_emits_xyz(self, tmp_path, monkeypatch):
        """version_patch=1 must produce '4.2.1-stable'."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=1)
        monkeypatch.setattr(config, "EXTENSION_API", api)
        tag = docs_mod._version_tag()
        assert tag == "4.2.1-stable", f"Expected '4.2.1-stable', got {tag!r}"

    def test_patch_zero_major_minor_correct(self, tmp_path, monkeypatch):
        """Major and minor are preserved regardless of patch value."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=3, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)
        tag = docs_mod._version_tag()
        assert tag.startswith("4.3-"), f"Major.minor must be 4.3: {tag!r}"

    def test_missing_api_returns_empty(self, tmp_path, monkeypatch):
        """A missing extension_api.json must return an empty string, not raise."""
        import godot_mcp.docs as docs_mod
        monkeypatch.setattr(config, "EXTENSION_API", tmp_path / "nonexistent.json")
        tag = docs_mod._version_tag()
        assert tag == "", f"Expected empty tag for missing api, got {tag!r}"

    def test_version_tag_cached(self, tmp_path, monkeypatch):
        """_version_tag() returns the same value on repeated calls (cached)."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)
        tag1 = docs_mod._version_tag()
        tag2 = docs_mod._version_tag()
        assert tag1 == tag2


# ---------------------------------------------------------------------------
# C19 — Version-keyed, crash-safe XML cache
# ---------------------------------------------------------------------------

class TestCacheLayout:
    """C19: cache files live under godot_docs/<tag>/<ClassName>.xml."""

    def test_cache_lands_under_tag_subdir(self, tmp_path, monkeypatch):
        """A successful fetch must write the cache file under godot_docs/<tag>/."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        xml = _minimal_xml("Node")
        fake_open = _fake_urlopen_ok(xml)
        monkeypatch.setattr(urllib.request, "urlopen", fake_open)

        result = docs_mod.class_docs("Node")
        assert result is not None, "Expected docs dict, got None"

        tag = "4.2-stable"
        expected_cache = docs_mod._CACHE / tag / "Node.xml"
        assert expected_cache.exists(), (
            f"Cache file not found at expected path: {expected_cache}"
        )

    def test_cache_subdir_created(self, tmp_path, monkeypatch):
        """The <tag> subdir is created if it does not exist."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        xml = _minimal_xml("Node")
        fake_open = _fake_urlopen_ok(xml)
        monkeypatch.setattr(urllib.request, "urlopen", fake_open)

        docs_mod.class_docs("Node")
        tag_dir = docs_mod._CACHE / "4.2-stable"
        assert tag_dir.is_dir()

    def test_malformed_xml_leaves_no_cache_file(self, tmp_path, monkeypatch):
        """A urlopen returning malformed XML must leave no file in the cache dir."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        fake_open = _fake_urlopen_malformed_xml()
        monkeypatch.setattr(urllib.request, "urlopen", fake_open)

        result = docs_mod.class_docs("Node")
        assert result is None, "Expected None for malformed XML"

        tag_dir = docs_mod._CACHE / "4.2-stable"
        if tag_dir.exists():
            cached = list(tag_dir.glob("*.xml"))
            assert len(cached) == 0, (
                f"Partial cache files found after malformed XML: {cached}"
            )

    def test_different_tag_does_not_read_first_tag_cache(self, tmp_path, monkeypatch):
        """A call for a different version tag must not read the first tag's cache file."""
        import godot_mcp.docs as docs_mod

        # Write a fake cache for tag 4.2-stable
        api_42 = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api_42)

        xml = _minimal_xml("Node")
        fake_open = _fake_urlopen_ok(xml)
        monkeypatch.setattr(urllib.request, "urlopen", fake_open)

        # Fetch for 4.2
        result_42 = docs_mod.class_docs("Node")
        assert result_42 is not None

        # Verify the 4.2 cache exists
        cache_42 = docs_mod._CACHE / "4.2-stable" / "Node.xml"
        assert cache_42.exists()

        # Now switch to version 4.3 — reset _tag and _mem so it re-reads
        monkeypatch.setattr(docs_mod, "_tag", None)
        monkeypatch.setattr(docs_mod, "_mem", {})
        api_43 = _make_extension_api(tmp_path, major=4, minor=3, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api_43)

        # 4.3 fetch will fail (fake urlopen raises 404 for this call — page doesn't exist)
        # We don't care about success here; we just want to confirm it does NOT
        # silently serve content from the 4.2 cache.
        call_count = [0]

        def _tracking_open(*args, **kwargs):
            call_count[0] += 1
            raise urllib.error.HTTPError(
                url="http://example.com", code=404, msg="Not Found",
                hdrs=None, fp=None  # type: ignore[arg-type]
            )

        monkeypatch.setattr(urllib.request, "urlopen", _tracking_open)

        result_43 = docs_mod.class_docs("Node")
        # 4.3 cache doesn't exist → must attempt a fetch (not serve 4.2 result)
        assert call_count[0] == 1, (
            "Expected urlopen to be called once for a new tag (not read old tag's cache), "
            f"got {call_count[0]} calls"
        )
        # Result must be None (404 → no docs) not the stale 4.2 data
        assert result_43 is None

    def test_second_call_same_class_same_tag_uses_cache(self, tmp_path, monkeypatch):
        """A second call for the same class + tag reads from disk cache, not network."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        xml = _minimal_xml("Sprite2D")
        fake_open = _fake_urlopen_ok(xml)
        monkeypatch.setattr(urllib.request, "urlopen", fake_open)

        # First call → network fetch
        docs_mod.class_docs("Sprite2D")
        # Clear in-memory cache to force a disk cache lookup on second call
        monkeypatch.setattr(docs_mod, "_mem", {})

        # Second call — urlopen should NOT be called again (disk cache hits)
        no_network = MagicMock(side_effect=AssertionError("Network called on second fetch"))
        monkeypatch.setattr(urllib.request, "urlopen", no_network)

        result = docs_mod.class_docs("Sprite2D")
        assert result is not None, "Expected cached docs on second call"


class TestAtomicWrite:
    """C19: writes are atomic — no partial file left on failure."""

    def test_no_partial_file_on_write_error(self, tmp_path, monkeypatch):
        """If the temp-write fails, no partial .xml file appears in the tag dir.

        We simulate a failure by monkeypatching Path.write_text on the temp file
        to raise. The implementation must clean up the temp before re-raising.
        """
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        # urlopen succeeds, returns valid XML
        xml = _minimal_xml("Node")
        fake_open = _fake_urlopen_ok(xml)
        monkeypatch.setattr(urllib.request, "urlopen", fake_open)

        # Patch os.replace to raise so the rename step fails
        import os as os_mod

        def _fail_replace(src: str, dst: str) -> None:
            raise OSError("Simulated rename failure")

        monkeypatch.setattr(os_mod, "replace", _fail_replace)

        result = docs_mod.class_docs("Node")
        # Should degrade gracefully (return None), not raise
        assert result is None

        # No partial file should exist under the tag dir
        tag_dir = docs_mod._CACHE / "4.2-stable"
        if tag_dir.exists():
            xml_files = list(tag_dir.glob("*.xml"))
            assert len(xml_files) == 0, f"Partial cache file found: {xml_files}"


# ---------------------------------------------------------------------------
# C20 — Process-wide network-down latch
# ---------------------------------------------------------------------------

class TestNetworkDownLatch:
    """C20: connection error (not 404) sets latch; subsequent calls skip fetch."""

    def test_connection_error_sets_latch(self, tmp_path, monkeypatch):
        """A socket.error must set the network-down latch."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_connection_error())
        docs_mod.class_docs("Node")

        assert docs_mod._network_down is True, (
            "Expected _network_down latch to be set after connection error"
        )

    def test_url_error_non_404_sets_latch(self, tmp_path, monkeypatch):
        """A URLError with non-HTTP reason must set the network-down latch."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_url_error_not_404())
        docs_mod.class_docs("Node")

        assert docs_mod._network_down is True

    def test_http_404_does_not_set_latch(self, tmp_path, monkeypatch):
        """A 404 HTTPError must NOT set the network-down latch."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_404())
        docs_mod.class_docs("Node")

        assert docs_mod._network_down is False, (
            "A 404 must NOT set the network-down latch"
        )

    def test_latch_prevents_subsequent_fetch(self, tmp_path, monkeypatch):
        """After a connection error, a subsequent class_docs call must NOT attempt a fetch.

        urlopen should be called exactly once (for the first failure), not again
        for the second class.
        """
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        call_count = [0]

        def _counting_error(*args, **kwargs):
            call_count[0] += 1
            raise socket.error("Network down")

        monkeypatch.setattr(urllib.request, "urlopen", _counting_error)

        # First call — sets the latch
        docs_mod.class_docs("Node")
        assert docs_mod._network_down is True
        assert call_count[0] == 1

        # Second call for a DIFFERENT class — must NOT call urlopen again
        docs_mod.class_docs("Sprite2D")
        assert call_count[0] == 1, (
            f"urlopen called {call_count[0]} times; expected 1 (latch should block second fetch)"
        )

    def test_latch_does_not_block_disk_cache(self, tmp_path, monkeypatch):
        """The network latch must not block a hit that is already in the disk cache."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        # Pre-populate the disk cache manually under the correct tag dir
        tag_dir = docs_mod._CACHE / "4.2-stable"
        tag_dir.mkdir(parents=True)
        (tag_dir / "Node.xml").write_text(_minimal_xml("Node"), encoding="utf-8")

        # Set the latch — simulates a prior connection failure
        monkeypatch.setattr(docs_mod, "_network_down", True)

        # Should still return docs from disk cache despite latch
        result = docs_mod.class_docs("Node")
        assert result is not None, (
            "Disk-cached docs should be returned even when network-down latch is set"
        )

    def test_404_result_is_none_not_cached_as_docs(self, tmp_path, monkeypatch):
        """A 404 response must produce None (no XML), not a bogus docs entry."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_404())
        result = docs_mod.class_docs("NonExistentClass")
        assert result is None

    def test_latch_second_call_returns_none(self, tmp_path, monkeypatch):
        """When the latch is set, subsequent calls return None (no network, no cache)."""
        import godot_mcp.docs as docs_mod
        api = _make_extension_api(tmp_path, major=4, minor=2, patch=0)
        monkeypatch.setattr(config, "EXTENSION_API", api)

        def _error(*args, **kwargs):
            raise socket.error("Network down")

        monkeypatch.setattr(urllib.request, "urlopen", _error)

        docs_mod.class_docs("Node")  # sets latch
        result = docs_mod.class_docs("Sprite2D")  # blocked by latch, no cache
        assert result is None
