from qfluentwidgets import EditableComboBox

from videocaptioner.ui.components.EditComboBoxSettingCard import (
    EditComboBoxSettingCard,
    MultiSelectEditableComboBox,
    _combo_box_class,
    _MultiSelectComboBoxMenu,
    _selection_values,
    _toggle_selection,
)


class _FakeSignal:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class _FakeCard:
    def __init__(self):
        self._updatingItems = False
        self.saved = []
        self.currentTextChanged = _FakeSignal()

    def setValue(self, value):
        self.saved.append(value)


class _FakeMultiSelectComboBox:
    def __init__(self, items, text, card):
        self.items = items
        self.text = text
        self.card = card
        self.activated = _FakeSignal()
        self.textActivated = _FakeSignal()

    def count(self):
        return len(self.items)

    def itemText(self, index):
        return self.items[index]

    def currentText(self):
        return self.text

    def setText(self, text):
        self.text = text
        EditComboBoxSettingCard._EditComboBoxSettingCard__onTextChanged(
            self.card, text
        )


def test_multi_select_click_appends_and_removes_in_priority_order():
    card = _FakeCard()
    combo = _FakeMultiSelectComboBox(
        ["primary", "backup-a", "backup-b"],
        "primary， backup-a, primary",
        card,
    )

    MultiSelectEditableComboBox._onItemClicked(combo, 2)
    assert combo.text == "primary, backup-a, backup-b"

    MultiSelectEditableComboBox._onItemClicked(combo, 1)
    assert combo.text == "primary, backup-b"
    assert combo.activated.values == [2, 1]
    assert combo.textActivated.values == ["backup-b", "backup-a"]
    assert card.saved == ["primary, backup-a, backup-b", "primary, backup-b"]
    assert card.currentTextChanged.values == card.saved


def test_multi_select_value_is_trimmed_and_deduplicated():
    assert _selection_values(" primary，backup, primary, ,third ") == [
        "primary",
        "backup",
        "third",
    ]
    assert _toggle_selection("", "primary") == "primary"
    assert _toggle_selection("primary, backup", "backup") == "primary"
    assert _toggle_selection("primary", "primary") == "primary"


def test_refreshing_items_preserves_value_without_intermediate_write():
    class FakeItemsComboBox:
        def __init__(self, card):
            self.card = card
            self.text = "primary, custom-model"
            self.items = []

        def _set_text(self, text):
            self.text = text
            EditComboBoxSettingCard._EditComboBoxSettingCard__onTextChanged(
                self.card, text
            )

        def currentText(self):
            return self.text

        def clear(self):
            self.items.clear()
            self._set_text("")

        def addItem(self, item):
            self.items.append(item)
            if len(self.items) == 1:
                self._set_text(item)

        def setText(self, text):
            self._set_text(text)

    class FakeItemsCard(_FakeCard):
        def __init__(self):
            super().__init__()
            self.items = []
            self.multiSelect = True
            self.completer_refreshes = 0
            self.comboBox = FakeItemsComboBox(self)

        def _setupCompleter(self):
            self.completer_refreshes += 1

    card = FakeItemsCard()
    EditComboBoxSettingCard.setItems(card, [" backup ", "backup", "third", ""])

    assert card.items == ["primary", "custom-model", "backup", "third"]
    assert card.comboBox.text == "primary, custom-model"
    assert card.saved == []
    assert card.currentTextChanged.values == []
    assert card.completer_refreshes == 1
    assert card._updatingItems is False


def test_multi_select_remains_opt_in_for_single_model_cards():
    assert _combo_box_class(False) is EditableComboBox
    assert _combo_box_class(True) is MultiSelectEditableComboBox


def test_multi_select_menu_triggers_without_closing():
    class FakeParent:
        def currentText(self):
            return "primary, backup"

    class FakeAction:
        def __init__(self):
            self.triggered = 0
            self.checked = False

        def isEnabled(self):
            return True

        def trigger(self):
            self.triggered += 1

        def text(self):
            return "backup"

        def setChecked(self, checked):
            self.checked = checked

    class FakeItem:
        def __init__(self, action):
            self.action = action

        def data(self, _role):
            return self.action

    class FakeViewport:
        def __init__(self):
            self.updates = 0

        def update(self):
            self.updates += 1

    action = FakeAction()
    viewport = FakeViewport()
    menu = type(
        "FakeMenu",
        (),
        {
            "menuActions": lambda self: [action],
            "parent": lambda self: FakeParent(),
            "view": type("FakeView", (), {"viewport": lambda self: viewport})(),
        },
    )()

    _MultiSelectComboBoxMenu._onItemClicked(menu, FakeItem(action))

    assert action.triggered == 1
    assert action.checked is True
    assert viewport.updates == 1
