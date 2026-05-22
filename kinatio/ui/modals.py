"""Interactive modal screens for Kinatio."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


def _centered_text(value: str) -> Text:
    return Text(value, justify="center")


class SudoPasswordModal(ModalScreen[str | None]):
    """Prompt for a sudo password inside the TUI."""

    CSS = """
    SudoPasswordModal {
        align: center middle;
    }

    #sudo-dialog {
        width: 72;
        max-width: 90%;
        border: round #641515;
        background: #111417;
        padding: 1 2;
        align-horizontal: center;
    }

    #sudo-actions {
        height: auto;
        width: 100%;
        align-horizontal: center;
        margin-top: 1;
    }

    #sudo-title,
    #sudo-body,
    #sudo-message {
        width: 100%;
    }

    #sudo-message {
        color: #8c949b;
        margin-top: 1;
    }

    #sudo-password {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Unlock"),
    ]

    def __init__(self, section: str, message: str | None = None) -> None:
        super().__init__()
        self.section = section
        self.message = message or "sudo credentials are required for this category."

    def compose(self) -> ComposeResult:
        with Vertical(id="sudo-dialog"):
            yield Static(_centered_text(f"Unlock {self.section}"), id="sudo-title")
            yield Static(
                _centered_text("Enter your sudo password to unlock this category for the current session."),
                id="sudo-body",
            )
            yield Static(_centered_text(self.message), id="sudo-message")
            yield Input(password=True, placeholder="sudo password", id="sudo-password")
            with Horizontal(id="sudo-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Unlock", id="submit", variant="error")

    def on_mount(self) -> None:
        self.query_one("#sudo-password", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        password_input = self.query_one("#sudo-password", Input)
        value = password_input.value
        password_input.value = ""
        self.dismiss(value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
            return
        self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sudo-password":
            self.action_submit()


class SearchModal(ModalScreen[str | None]):
    """Prompt for a search query used by interactive section filters."""

    CSS = SudoPasswordModal.CSS.replace("SudoPasswordModal", "SearchModal").replace("sudo", "search")

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("enter", "submit", "Apply"),
    ]

    def __init__(self, section: str, current_query: str = "") -> None:
        super().__init__()
        self.section = section
        self.current_query = current_query

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Static(_centered_text(f"Filter {self.section}"), id="search-title")
            yield Static(
                _centered_text("Enter text to filter the interactive list. Submit an empty value to clear the filter."),
                id="search-body",
            )
            yield Input(value=self.current_query, placeholder="type to filter", id="search-query")
            with Horizontal(id="search-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Clear", id="clear")
                yield Button("Apply", id="submit", variant="error")

    def on_mount(self) -> None:
        self.query_one("#search-query", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self.dismiss(self.query_one("#search-query", Input).value.strip())

    def action_clear(self) -> None:
        self.dismiss("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
            return
        if event.button.id == "clear":
            self.action_clear()
            return
        self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-query":
            self.action_submit()