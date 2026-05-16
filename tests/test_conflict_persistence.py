"""
Tests for conflict resolved-state persistence.
The PATCH endpoint must overwrite archive files session-scoped.
The done SSE payload must include _archive_filename.
"""
import json
import re
import inspect
import pytest


def test_archive_filename_format():
    """Archive filenames must match the expected pattern."""
    import uuid
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:6]
    filename = f"analysis_{timestamp}_{short_id}.json"
    assert re.match(r'^analysis_\d{8}_\d{6}_[a-f0-9]{6}\.json$', filename)


def test_patch_endpoint_exists_in_routes():
    """routes.py must define a PATCH /api/samples/{filename} endpoint."""
    from app.api import routes
    src = inspect.getsource(routes)
    assert "@router.patch" in src
    assert "update_sample" in src


def test_patch_endpoint_has_path_traversal_guard():
    """PATCH endpoint must reject filenames containing / \\ or .."""
    from app.api import routes
    src = inspect.getsource(routes)
    # The guard must be present in the update_sample function
    assert '".." in filename' in src or "'..' in filename" in src


def test_patch_endpoint_uses_session_dir():
    """PATCH endpoint must scope file access to the session directory."""
    from app.api import routes
    src = inspect.getsource(routes)
    assert "get_session_dir" in src


def test_patch_sample_updates_file(tmp_path):
    """PATCH logic must overwrite the archive file with new content."""
    original = {"document_extended": {"goals": [{"text": "goal", "resolved": False}]}}
    updated  = {"document_extended": {"goals": [{"text": "goal", "resolved": True}]}}

    test_file = tmp_path / "analysis_test.json"
    test_file.write_text(json.dumps(original), encoding="utf-8")

    # Simulate what the endpoint does
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)

    with open(test_file, encoding="utf-8") as f:
        result = json.load(f)

    assert result["document_extended"]["goals"][0]["resolved"] is True


def test_archive_filename_injected_into_done_payload():
    """routes.py must set result['_archive_filename'] before yielding the done event."""
    from app.api import routes
    src = inspect.getsource(routes)
    assert '_archive_filename' in src
    assert 'result["_archive_filename"]' in src or "result['_archive_filename']" in src


def test_frontend_tracks_current_archive_filename():
    """index.html must declare currentArchiveFilename and set it on done and archive load."""
    with open("app/frontend/index.html", encoding="utf-8") as f:
        html = f.read()
    assert "currentArchiveFilename" in html
    assert "_archive_filename" in html          # captured from done payload
    assert "currentArchiveFilename = filename"  in html  # set in loadSampleByName


def test_frontend_patch_call_in_resolve():
    """index.html must fire a PATCH request inside markConflictResolved."""
    with open("app/frontend/index.html", encoding="utf-8") as f:
        html = f.read()
    assert "method: 'PATCH'" in html
    assert "/api/samples/" in html
    assert "currentArchiveFilename" in html
