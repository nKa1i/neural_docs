def test_non_data_set_is_english():
    """llm_provider must not contain Russian fallback strings."""
    from app.services import llm_provider
    import inspect
    source = inspect.getsource(llm_provider)
    assert "нет данных" not in source.lower(), \
        "Russian 'нет данных' must not appear anywhere in llm_provider"
    assert '"no data"' in source.lower(), "English 'no data' must be present"
