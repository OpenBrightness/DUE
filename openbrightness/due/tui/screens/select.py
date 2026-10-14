"""Interactive display picker screen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from openbrightness.due.models import OutputInfo


class DisplayListItem(ListItem):
    def __init__(self, output: OutputInfo) -> None:
        super().__init__()
        self.output = output

    def compose(self) -> ComposeResult:
        marker = "● " if self.output.is_primary else "  "
        yield Label(
            f"{marker}{self.output.connector}  "
            f"{self.output.make} {self.output.model}  "
            f"{self.output.width}×{self.output.height} @ {self.output.refresh_rate:.0f} Hz"
        )


class DisplaySelectScreen(Screen[None]):
    """Lets the user pick which output to analyze."""

    BINDINGS: ClassVar[list[BindingType]] = [("q", "quit_app", "Quit")]

    DEFAULT_CSS = """
    #select-title {
        padding: 1 2;
    }
    #output-list {
        height: auto;
        max-height: 1fr;
        padding: 0 2;
        border: round $primary;
    }
    """

    def __init__(self, outputs: list[OutputInfo]) -> None:
        super().__init__()
        self._outputs = outputs
        self.selected: OutputInfo | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("[b]Select a display to analyze[/b]\n", id="select-title")
        yield ListView(*(DisplayListItem(o) for o in self._outputs), id="output-list")
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, DisplayListItem):
            self.selected = item.output
            self.post_message(self.DisplayChosen(item.output))

    def action_quit_app(self) -> None:
        self.post_message(self.QuitApp())

    class DisplayChosen(Message):
        def __init__(self, output: OutputInfo) -> None:
            super().__init__()
            self.output = output

    class QuitApp(Message):
        pass
