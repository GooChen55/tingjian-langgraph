import pytest

@pytest.fixture(autouse=True)
def isolated_model_store(tmp_path, monkeypatch):
    monkeypatch.setenv('LISTENING_MODEL_SETTINGS_FILE', str(tmp_path / 'model-settings.json'))
