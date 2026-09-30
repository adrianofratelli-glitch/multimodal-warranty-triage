import pytest

from storage import URI_SCHEME, path_for, url_for


def test_url_for_converts_uri_to_public_url():
    uri = f"{URI_SCHEME}chamados/CHM-2026-0001/foto.jpg"
    assert url_for(uri) == "/media/chamados/CHM-2026-0001/foto.jpg"


def test_path_for_strips_scheme_and_joins_media_root():
    key = "chamados/CHM-2026-0001/foto.jpg"
    resolved = path_for(key)
    assert str(resolved).endswith("chamados/CHM-2026-0001/foto.jpg")


@pytest.mark.parametrize("key", ["../outside.jpg", "folder/../../../outside.jpg"])
def test_path_for_rejects_traversal(key):
    with pytest.raises(ValueError, match="invalid media storage key"):
        path_for(key)
