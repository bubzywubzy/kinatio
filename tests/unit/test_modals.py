from kinatio.ui.modals import SearchModal, SudoPasswordModal


class _DummyInput:
    def __init__(self, value: str) -> None:
        self.value = value


def test_sudo_password_modal_clears_input_before_dismiss(monkeypatch) -> None:
    modal = SudoPasswordModal("Logs")
    password_input = _DummyInput("hunter2")
    dismissed: list[str | None] = []

    monkeypatch.setattr(modal, "query_one", lambda *args, **kwargs: password_input)
    monkeypatch.setattr(modal, "dismiss", lambda value: dismissed.append(value))

    modal.action_submit()

    assert dismissed == ["hunter2"]
    assert password_input.value == ""


def test_search_modal_clear_action_dismisses_empty_query(monkeypatch) -> None:
    modal = SearchModal("Processes", current_query="ssh")
    dismissed: list[str | None] = []

    monkeypatch.setattr(modal, "dismiss", lambda value: dismissed.append(value))

    modal.action_clear()

    assert dismissed == [""]


def test_modal_css_centers_dialog_actions_and_full_width_copy() -> None:
    css = SudoPasswordModal.CSS

    assert "align-horizontal: center;" in css
    assert "#sudo-title," in css
    assert "#sudo-body," in css
    assert "#sudo-message" in css
    assert "#sudo-actions" in css and "width: 100%;" in css
    assert "#sudo-password" in css and "width: 100%;" in css