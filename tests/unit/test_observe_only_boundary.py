import importlib
import inspect

import pytest
from textual.screen import ModalScreen

from kinatio.app import KinatioApp
from kinatio.domain import models
from kinatio.ui import modals


@pytest.mark.parametrize(
    "module_name",
    [
        "kinatio.engine.audit",
        "kinatio.engine.plans",
        "kinatio.engine.policy",
        "kinatio.engine.registry",
    ],
)
def test_removed_control_plane_modules_stay_absent(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize(
    "attribute_name",
    [
        "ActionResult",
        "AuditRecord",
        "CapabilityDescriptor",
        "ChangePlan",
        "ChangePlanStep",
        "ChangeRequest",
        "PolicyDecision",
        "ValidationIssue",
    ],
)
def test_removed_control_plane_models_stay_absent(attribute_name: str) -> None:
    assert not hasattr(models, attribute_name)


def test_tui_only_exposes_observe_only_actions() -> None:
    action_names = {name for name in KinatioApp.__dict__ if name.startswith("action_")}

    assert action_names == {
        "action_cycle_sort",
        "action_navigate_back",
        "action_open_selected_item",
        "action_refresh_now",
        "action_search_detail",
        "action_toggle_focus",
        "action_toggle_follow",
        "action_toggle_live_updates",
        "action_toggle_log_noise",
        "action_unlock_section",
    }


def test_tui_modal_surface_stays_limited_to_search_and_unlock() -> None:
    modal_names = {
        name
        for name, value in modals.__dict__.items()
        if inspect.isclass(value)
        and issubclass(value, ModalScreen)
        and value.__module__ == modals.__name__
    }

    assert modal_names == {"SearchModal", "SudoPasswordModal"}