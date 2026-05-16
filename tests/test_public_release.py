def test_get_loaded_model_returns_first_model():
    """_get_loaded_model returns the first model ID from /v1/models."""
    from app.services.llm_provider import LocalProvider
    from unittest.mock import patch, MagicMock
    provider = LocalProvider(base_url="http://localhost:1234/v1", model_name=None, api_key="test")

    mock_model = MagicMock()
    mock_model.id = "qwen2.5-7b-instruct"
    mock_response = MagicMock()
    mock_response.data = [mock_model]

    with patch.object(provider.client.models, 'list', return_value=mock_response):
        assert provider._get_loaded_model() == "qwen2.5-7b-instruct"


def test_get_loaded_model_fallback_on_error():
    """_get_loaded_model returns 'local-model' when /v1/models fails."""
    from app.services.llm_provider import LocalProvider
    from unittest.mock import patch
    provider = LocalProvider(base_url="http://localhost:1234/v1", model_name=None, api_key="test")

    with patch.object(provider.client.models, 'list', side_effect=Exception("connection refused")):
        assert provider._get_loaded_model() == "local-model"


def test_non_data_set_is_english():
    """llm_provider must not contain Russian fallback strings."""
    from app.services import llm_provider
    import inspect
    source = inspect.getsource(llm_provider)
    assert "нет данных" not in source.lower(), \
        "Russian 'нет данных' must not appear anywhere in llm_provider"
    assert '"no data"' in source.lower(), "English 'no data' must be present"
