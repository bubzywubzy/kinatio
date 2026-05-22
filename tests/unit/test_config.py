import pytest
from pydantic import ValidationError

from kinatio.config import AppConfig, DEFAULT_CONFIG


def test_app_config_instances_are_frozen() -> None:
    config = AppConfig()

    with pytest.raises(ValidationError):
        config.max_log_entries = 42  # type: ignore[misc]



def test_default_config_rejects_attribute_reassignment() -> None:
    with pytest.raises(ValidationError):
        DEFAULT_CONFIG.ui_refresh_interval = 2.0  # type: ignore[misc]
