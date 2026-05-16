import pytest
from unittest.mock import patch, MagicMock


def test_non_data_set_is_english():
    """NON_DATA_LC in llm_provider must not contain Russian strings."""
    from app.services import llm_provider
    import inspect
    source = inspect.getsource(llm_provider)
    assert "нет данных" not in source.lower() or "NON_DATA_LC" not in source, \
        "Russian 'нет данных' must be removed from NON_DATA_LC"
    assert '"no data"' in source.lower(), "English 'no data' must be present"
