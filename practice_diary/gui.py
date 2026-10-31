"""Графический интерфейс (PySide6)."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSettings, QSortFilterProxyModel, Qt,
                            QUrl)
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QSplitter, QStyledItemDelegate, QTableView,
                               QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget)

from .diary import DEFAULT_TEMPLATE, DiaryOptions, generate_diary
from .models import COLUMNS, HEADER_FIELDS, Group, Student
from .places import PlaceEntry, PlacesBook, normalize
from .predstavlenie import Predstavlenie

ORG_COL_TITLE = "Руководитель от организации"
MULTILINE_KEYS = {"place", "okved", "practice_type"}


# ====================== модель таблицы ======================

class StudentsModel(QAbstractTableModel):
    # колонки: [отметка, группа, поля представления..., руководитель от организации]
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[Group, Student]] = []
        self.checked: set[int] = set()  # id(Student)
        self.places: PlacesBook | None = None
        self.on_change = lambda: None

    def org_head(self, s: Student) -> str:
        return self.places.head_for(s.get("place")) if self.places else ""

    def set_data(self, pr: Predstavlenie | None):
        self.beginResetModel()
        self.rows = [(g, s) for g in pr.groups for s in g.students] if pr else []
        alive = {id(s) for _, s in self.rows}
        self.checked &= alive
        self.endResetModel()

    # --- служебное ---
    def columnCount(self, parent=QModelIndex()):
        return 2 + len(COLUMNS) + 1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def column_key(self, col: int) -> str:
        if col == 0:
            return "_check"
        if col == 1:
            return "_group"
        if col == 2 + len(COLUMNS):
            return "_org"
        return COLUMNS[col - 2][0]

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            key = self.column_key(section)
            return {"_check": "✓", "_group": "Группа", "_org": ORG_COL_TITLE}.get(
                key, dict(COLUMNS).get(key))
        if orientation == Qt.Vertical and role == Qt.DisplayRole:
            return section + 1
        return None

    def flags(self, index):
        key = self.column_key(index.column())
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if key == "_check":
            return f | Qt.ItemIsUserCheckable
        if key in ("_group", "_org"):
            return f
        return f | Qt.ItemIsEditable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        g, s = self.rows[index.row()]
        key = self.column_key(index.column())
        if role == Qt.CheckStateRole and key == "_check":
            return Qt.Checked if id(s) in self.checked else Qt.Unchecked
        if role in (Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole):
            if key == "_check":
                return None
            if key == "_group":
                return g.name
            if key == "_org":
                if role == Qt.ToolTipRole:
                    return "Задаётся в меню «Справочники → Руководители по местам практики»"
                return self.org_head(s)
            text = s.get(key)
            if role == Qt.DisplayRole:
                text = text.replace("\n", " ")
                if key == "name" and not text:
                    return "‹ФИО не заполнено›"
            return text
        return None

    def setData(self, index, value, role=Qt.EditRole):
        g, s = self.rows[index.row()]
        key = self.column_key(index.column())
        if role == Qt.CheckStateRole and key == "_check":
            checked = value in (Qt.Checked, Qt.Checked.value, 2, True)
            (self.checked.add if checked else self.checked.discard)(id(s))
            self.dataChanged.emit(index, index)
            return True
        if role != Qt.EditRole:
            return False
        value = (value or "").strip()
        if s.get(key) == value:
            return False
        s.values[key] = value
        self.dataChanged.emit(index, index)
        self.on_change()
        return True

    def checked_rows(self) -> list[tuple[Group, Student]]:
        return [(g, s) for g, s in self.rows if id(s) in self.checked]


class FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.group: Group | None = None
        self.text = ""

    def filterAcceptsRow(self, row, parent):
        g, s = self.sourceModel().rows[row]
        if self.group is not None and g is not self.group:
            return False
        if self.text:
            hay = " ".join([g.name, self.sourceModel().org_head(s), *s.values.values()]).lower()
            return all(w in hay for w in self.text.lower().split())
        return True


class TextDelegate(QStyledItemDelegate):
    """Многострочный редактор для длинных полей."""

    def createEditor(self, parent, option, index):
        key = index.model().sourceModel().column_key(
            index.model().mapToSource(index).column())
        text = index.data(Qt.EditRole) or ""
        if key in MULTILINE_KEYS or "\n" in text:
            ed = QPlainTextEdit(parent)
            ed.setMinimumHeight(70)
            return ed
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QPlainTextEdit):
            editor.setPlainText(index.data(Qt.EditRole) or "")
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QPlainTextEdit):
            model.setData(index, editor.toPlainText(), Qt.EditRole)
        else:
            super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        if isinstance(editor, QPlainTextEdit):
            r.setHeight(max(r.height(), 80))
        editor.setGeometry(r)


# ====================== справочник руководителей ======================

class PlacesDialog(QDialog):
    """Руководители от профильной организации по местам практики.

    Показывает все места из справочника и из открытого представления. Руководитель
    вписывается один раз на место и сразу сохраняется в справочник.
    """
    COL_PLACE, COL_HEAD, COL_COUNT = range(3)

    def __init__(self, book: PlacesBook, pr: Predstavlenie | None, settings: QSettings,
                 parent=None, focus_place: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Руководители по местам практики")
        self.resize(900, 560)
        self.book, self.pr, self.settings = book, pr, settings
        self._filling = False
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Впишите руководителя от профильной организации для каждого места — он будет "
            "подставляться в дневники всех студентов этого места. Изменения сохраняются сразу."))

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск места или руководителя…")
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search, 1)
        self.only_empty = QCheckBox("Только без руководителя")
        self.only_empty.toggled.connect(self.apply_filter)
        top.addWidget(self.only_empty)
        lay.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Место проведения практики", "Руководитель от организации", "Студентов в файле"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_PLACE, QHeaderView.Stretch)
        hh.setSectionResizeMode(self.COL_HEAD, QHeaderView.Interactive)
        hh.setSectionResizeMode(self.COL_COUNT, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(self.COL_HEAD, 240)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.itemChanged.connect(self.item_changed)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        b_imp = QPushButton("📥 Загрузить из Excel…")
        b_imp.clicked.connect(self.import_excel)
        b_add = QPushButton("➕ Добавить место")
        b_add.clicked.connect(self.add_place)
        b_del = QPushButton("➖ Удалить из справочника")
        b_del.clicked.connect(self.delete_place)
        for b in (b_imp, b_add, b_del):
            btns.addWidget(b)
        btns.addStretch(1)
        self.info = QLabel()
        btns.addWidget(self.info)
        b_close = QPushButton("Закрыть")
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_close)
        lay.addLayout(btns)

        self.fill()
        if focus_place:
            self.focus(focus_place)

    # ---------- данные ----------
    def _file_places(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        if self.pr:
            for g in self.pr.groups:
                for st in g.students:
                    pl = st.get("place").replace("\n", " ").strip()
                    if pl and st.get("name"):
                        counts[pl] = counts.get(pl, 0) + 1
        return counts

    def fill(self):
        """Строки: записи справочника + места из файла, которых в справочнике нет."""
        rows = []  # (place, head, count, entry|None)
        per_entry: dict[int, int] = {}
        unmatched: dict[str, list] = {}  # нормализованное название -> [текст, кол-во]
        for pl, n in self._file_places().items():
            e = self.book.find(pl)
            if e is None:
                slot = unmatched.setdefault(normalize(pl), [pl, 0])
                slot[1] += n
            else:
                per_entry[id(e)] = per_entry.get(id(e), 0) + n
        for e in self.book.entries:
            rows.append((e.place, e.head, per_entry.get(id(e), 0), e))
        for pl, n in unmatched.values():
            rows.append((pl, "", n, None))
        # сначала места из файла без руководителя, затем по алфавиту
        rows.sort(key=lambda r: (not (r[2] and not r[1]), r[2] == 0, r[0].lower()))

        self._filling = True
        self.table.setRowCount(len(rows))
        for i, (pl, head, n, e) in enumerate(rows):
            it_pl = QTableWidgetItem(pl)
            it_pl.setData(Qt.UserRole, e)
            if e is None:
                it_pl.setFlags(it_pl.flags() & ~Qt.ItemIsEditable)
                it_pl.setToolTip("Место из открытого представления, пока не в справочнике")
            it_head = QTableWidgetItem(head)
            it_n = QTableWidgetItem(str(n) if n else "")
            it_n.setFlags(it_n.flags() & ~Qt.ItemIsEditable)
            it_n.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_PLACE, it_pl)
            self.table.setItem(i, self.COL_HEAD, it_head)
            self.table.setItem(i, self.COL_COUNT, it_n)
        self._filling = False
        self.table.resizeRowsToContents()
        self.apply_filter()

    def _update_info(self):
        missing = sum(1 for i in range(self.table.rowCount())
                      if self.table.item(i, self.COL_COUNT).text()
                      and not self.table.item(i, self.COL_HEAD).text().strip())
        self.info.setText(f"Мест в справочнике: {len(self.book.entries)}   |   "
                          f"мест из файла без руководителя: {missing}")

    def apply_filter(self, *_):
        words = self.search.text().lower().split()
        for i in range(self.table.rowCount()):
            pl = self.table.item(i, self.COL_PLACE).text().lower()
            head = self.table.item(i, self.COL_HEAD).text()
            hide = bool(words) and not all(w in f"{pl} {head.lower()}" for w in words)
            if self.only_empty.isChecked() and head.strip():
                hide = True
            self.table.setRowHidden(i, hide)
        self._update_info()

    def focus(self, place: str):
        target = self.book.find(place)
        for i in range(self.table.rowCount()):
            it = self.table.item(i, self.COL_PLACE)
            e = it.data(Qt.UserRole)
            if (target is not None and e is target) or (e is None and it.text() == place.strip()):
                self.table.setCurrentCell(i, self.COL_HEAD)
                self.table.scrollToItem(it)
                self.table.editItem(self.table.item(i, self.COL_HEAD))
                return

    # ---------- изменения ----------
    def item_changed(self, item: QTableWidgetItem):
        if self._filling:
            return
        row = item.row()
        it_pl = self.table.item(row, self.COL_PLACE)
        entry = it_pl.data(Qt.UserRole)
        place = it_pl.text().strip()
        head = self.table.item(row, self.COL_HEAD).text().strip()
        if entry is None:
            if item.column() != self.COL_HEAD or not head:
                return
            entry = self.book.set_head(place, head)
            self._filling = True
            it_pl.setData(Qt.UserRole, entry)
            it_pl.setFlags(it_pl.flags() | Qt.ItemIsEditable)
            it_pl.setToolTip("")
            self._filling = False
        else:
            if not place:
                self._filling = True
                it_pl.setText(entry.place)
                self._filling = False
                return
            entry.place, entry.head = place, head
        self._save()
        self._update_info()

    def _save(self):
        try:
            self.book.save()
        except OSError as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить справочник:\n{e}")

    def add_place(self):
        self.book.entries.append(PlaceEntry("Новое место", ""))
        self._save()
        self.fill()
        for i in range(self.table.rowCount()):
            if self.table.item(i, self.COL_PLACE).text() == "Новое место":
                self.table.setRowHidden(i, False)
                self.table.setCurrentCell(i, self.COL_PLACE)
                self.table.editItem(self.table.item(i, self.COL_PLACE))
                break

    def delete_place(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        entries = [self.table.item(r, self.COL_PLACE).data(Qt.UserRole) for r in rows]
        entries = [e for e in entries if e is not None]
        if not entries:
            return
        names = "\n".join(e.place for e in entries)
        if QMessageBox.question(self, "Удаление", f"Удалить из справочника:\n{names}?") \
                != QMessageBox.Yes:
            return
        for e in entries:
            self.book.remove(e)
        self._save()
        self.fill()

    def import_excel(self):
        f, _ = QFileDialog.getOpenFileName(self, "Excel с руководителями",
                                           self.settings.value("excel_dir", str(Path.home())),
                                           "Excel (*.xlsx *.xlsm)")
        if not f:
            return
        self.settings.setValue("excel_dir", str(Path(f).parent))
        try:
            added, updated = self.book.import_excel(f)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать Excel:\n{e}")
            return
        self._save()
        self.fill()
        QMessageBox.information(self, "Загрузка из Excel",
                                f"Добавлено мест: {added}\nОбновлено руководителей: {updated}")


# ====================== диалог генерации ======================

class GenerateDialog(QDialog):
    def __init__(self, rows, settings: QSettings, places: PlacesBook, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создание дневников")
        self.resize(640, 520)
        self.rows = rows
        self.settings = settings
        self.places = places
        lay = QVBoxLayout(self)

        lst = QListWidget()
        for g, s in rows:
            warn = "" if places.head_for(s.get("place")) else \
                "   (нет руководителя от организации — заполните справочник)"
            lst.addItem(f"{s.get('name')} — {g.name}{warn}")
        box = QGroupBox(f"Выбрано студентов: {len(rows)}")
        bl = QVBoxLayout(box)
        bl.addWidget(lst)
        lay.addWidget(box)

        form = QFormLayout()
        self.template = QLineEdit(settings.value("template", str(DEFAULT_TEMPLATE)))
        form.addRow("Шаблон дневника:", self._with_button(self.template, self._pick_template))
        self.outdir = QLineEdit(settings.value("outdir", str(Path.home() / "Дневники")))
        form.addRow("Папка для файлов:", self._with_button(self.outdir, self._pick_outdir))
        self.pattern = QLineEdit(settings.value("pattern", "Дневник_{surname}_{group}.docx"))
        self.pattern.setToolTip("Доступно: {surname} {name} {short_name} {group}")
        form.addRow("Имя файла:", self.pattern)
        self.gender = QCheckBox("Согласовать род в отзыве (Студент/Студентка, прошел/прошла …)")
        self.gender.setChecked(settings.value("gender", "true") == "true")
        form.addRow(self.gender)
        self.unhl = QCheckBox("Убрать жёлтое выделение в созданных файлах")
        self.unhl.setChecked(settings.value("unhl", "false") == "true")
        form.addRow(self.unhl)
        self.open_after = QCheckBox("Открыть папку после создания")
        self.open_after.setChecked(True)
        form.addRow(self.open_after)
        lay.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Создать")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _with_button(edit, slot):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(slot)
        h.addWidget(b)
        return w

    def _pick_template(self):
        f, _ = QFileDialog.getOpenFileName(self, "Шаблон дневника", self.template.text(),
                                           "Word (*.docx)")
        if f:
            self.template.setText(f)

    def _pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для дневников", self.outdir.text())
        if d:
            self.outdir.setText(d)

    def options(self) -> DiaryOptions:
        s = self.settings
        s.setValue("template", self.template.text())
        s.setValue("outdir", self.outdir.text())
        s.setValue("pattern", self.pattern.text())
        s.setValue("gender", "true" if self.gender.isChecked() else "false")
        s.setValue("unhl", "true" if self.unhl.isChecked() else "false")
        return DiaryOptions(template=Path(self.template.text()),
                            output_dir=Path(self.outdir.text()),
                            filename_pattern=self.pattern.text() or "Дневник_{surname}_{group}.docx",
                            gender_agreement=self.gender.isChecked(),
                            places=self.places)


# ====================== главное окно ======================

class MainWindow(QMainWindow):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.settings = QSettings("practice_diary", "practice_diary")
        self.pr: Predstavlenie | None = None
        self.dirty = False
        self.places = PlacesBook.load()
        self.resize(1400, 800)

        self.model = StudentsModel(self)
        self.model.on_change = self.mark_dirty
        self.model.places = self.places
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self._build_ui()
        self._update_title()
        if path:
            self.open_file(path)

    # ---------- интерфейс ----------
    def _build_ui(self):
        tb = QToolBar("Основное")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, shortcut=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            tb.addAction(a)
            return a

        act("📂 Открыть", self.choose_file, QKeySequence.Open)
        act("💾 Сохранить", self.save, QKeySequence.Save)
        act("Сохранить как…", self.save_as, QKeySequence.SaveAs)
        tb.addSeparator()
        act("➕ Добавить студента", self.add_student)
        act("➖ Удалить студента", self.delete_student, QKeySequence.Delete)
        tb.addSeparator()
        act("📝 Создать дневники для отмеченных", self.generate)
        tb.addSeparator()
        act("👤 Руководители по местам", self.edit_places)

        # меню
        mb = self.menuBar()
        m_file = mb.addMenu("Файл")
        for text, slot, sc in (("Открыть представление…", self.choose_file, QKeySequence.Open),
                               ("Сохранить", self.save, None),
                               ("Сохранить как…", self.save_as, None)):
            a = m_file.addAction(text)
            a.triggered.connect(slot)
        m_file.addSeparator()
        m_file.addAction("Выход").triggered.connect(self.close)
        m_ref = mb.addMenu("Справочники")
        m_ref.addAction("Руководители по местам практики…").triggered.connect(self.edit_places)
        m_ref.addAction("Загрузить руководителей из Excel…").triggered.connect(
            lambda: self.edit_places(import_now=True))

        splitter = QSplitter()
        # слева — группы и шапка
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Группы</b>"))
        self.groups = QListWidget()
        self.groups.currentRowChanged.connect(self.group_selected)
        ll.addWidget(self.groups, 1)
        self.header_box = QGroupBox("Сведения о группе")
        self.header_form = QFormLayout(self.header_box)
        self.header_edits: dict[str, QLineEdit] = {}
        for key, title in HEADER_FIELDS:
            e = QLineEdit()
            e.editingFinished.connect(lambda k=key, w=e: self.header_edited(k, w))
            self.header_edits[key] = e
            lbl = QLabel(title + ":")
            lbl.setWordWrap(True)
            self.header_form.addRow(lbl, e)
        self.header_box.setEnabled(False)
        ll.addWidget(self.header_box)
        splitter.addWidget(left)

        # справа — таблица студентов
        right = QWidget()
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по ФИО, месту, руководителю…")
        self.search.textChanged.connect(self.filter_changed)
        top.addWidget(self.search, 1)
        b1 = QPushButton("Отметить видимых")
        b1.clicked.connect(lambda: self.check_visible(True))
        b2 = QPushButton("Снять отметки")
        b2.clicked.connect(lambda: self.check_visible(False))
        top.addWidget(b1)
        top.addWidget(b2)
        rl.addLayout(top)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(TextDelegate(self.table))
        self.table.doubleClicked.connect(self.table_double_clicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        # «Руководитель от организации» — сразу после ФИО: его чаще всего нужно заполнять
        hh.moveSection(2 + len(COLUMNS), 3)
        rl.addWidget(self.table, 1)

        self.status = QLabel()
        rl.addWidget(self.status)
        legend = QLabel("Двойной щелчок — редактировать ячейку. Руководитель от организации "
                        "берётся из меню «Справочники → Руководители по местам практики» "
                        "(двойной щелчок по его ячейке открывает справочник).")
        legend.setWordWrap(True)
        rl.addWidget(legend)
        splitter.addWidget(right)
        splitter.setSizes([330, 1070])
        self.setCentralWidget(splitter)
        self.model.dataChanged.connect(lambda *a: self._update_status())

    def _resize_columns(self):
        widths = [30, 95, 230, 150, 150, 230, 90, 110, 260, 200]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        self.table.resizeRowsToContents()

    def _update_title(self):
        name = self.pr.path.name if self.pr else "файл не открыт"
        self.setWindowTitle(f"Дневники практики — {name}{' *' if self.dirty else ''}")

    def _update_status(self):
        total = len(self.model.rows)
        self.status.setText(f"Показано: {self.proxy.rowCount()} из {total}   |   "
                            f"Отмечено для дневников: {len(self.model.checked)}")

    def mark_dirty(self):
        self.dirty = True
        self._update_title()

    # ---------- файл ----------
    def choose_file(self):
        if not self.confirm_discard():
            return
        f, _ = QFileDialog.getOpenFileName(self, "Открыть представление",
                                           self.settings.value("last_dir", str(Path.home())),
                                           "Word (*.docx)")
        if f:
            self.open_file(f)

    def open_file(self, path):
        try:
            pr = Predstavlenie.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")
            return
        if not pr.groups:
            QMessageBox.warning(self, "Нет данных",
                                "В документе не найдено таблиц со столбцом «ФИО обучающихся».")
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.pr = pr
        self.dirty = False
        self.reload_view()

    def reload_view(self, keep_group: int | None = None):
        self.model.set_data(self.pr)
        self.groups.blockSignals(True)
        self.groups.clear()
        total = sum(len(g.students) for g in self.pr.groups) if self.pr else 0
        self.groups.addItem(QListWidgetItem(f"Все группы ({total})"))
        for g in (self.pr.groups if self.pr else []):
            self.groups.addItem(QListWidgetItem(f"{g.name} ({len(g.students)})"))
        self.groups.blockSignals(False)
        self.groups.setCurrentRow(keep_group if keep_group is not None else 0)
        self.group_selected(self.groups.currentRow())
        self._resize_columns()
        self._update_title()
        self._update_status()

    def save(self):
        if not self.pr:
            return
        self._save_to(None)

    def save_as(self):
        if not self.pr:
            return
        f, _ = QFileDialog.getSaveFileName(self, "Сохранить как", str(self.pr.path), "Word (*.docx)")
        if f:
            self._save_to(f)

    def _save_to(self, target):
        self.table.setFocus()  # завершить редактирование ячейки
        row = self.groups.currentRow()
        try:
            out = self.pr.save(target)
        except PermissionError:
            QMessageBox.critical(self, "Ошибка", "Нет доступа к файлу. Возможно, он открыт в Word.")
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"{e}\n\n{traceback.format_exc()}")
            return
        self.dirty = False
        self.reload_view(row)
        self.statusBar().showMessage(f"Сохранено: {out}", 5000)

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Несохранённые изменения", "Сохранить изменения?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            self.save()
            return not self.dirty
        return r == QMessageBox.Discard

    def closeEvent(self, ev):
        if self.confirm_discard():
            ev.accept()
        else:
            ev.ignore()

    # ---------- группы ----------
    def current_group(self) -> Group | None:
        i = self.groups.currentRow()
        if not self.pr or i <= 0:
            return None
        return self.pr.groups[i - 1]

    def group_selected(self, _row):
        g = self.current_group()
        self.proxy.group = g
        self.proxy.invalidateFilter()
        self.header_box.setEnabled(g is not None)
        for key, e in self.header_edits.items():
            e.setText(g.header.get(key, "") if g else "")
        self.table.resizeRowsToContents()
        self._update_status()

    def header_edited(self, key, widget):
        g = self.current_group()
        if g is None:
            return
        if g.header.get(key, "") != widget.text().strip():
            g.header[key] = widget.text().strip()
            self.mark_dirty()
            if key == "faculty_line":  # название группы могло измениться
                self.reload_view(self.groups.currentRow())

    def filter_changed(self, text):
        self.proxy.text = text
        self.proxy.invalidateFilter()
        self._update_status()

    def check_visible(self, state: bool):
        for r in range(self.proxy.rowCount()):
            src = self.proxy.mapToSource(self.proxy.index(r, 0))
            _, s = self.model.rows[src.row()]
            if state and s.get("name"):
                self.model.checked.add(id(s))
            elif not state:
                self.model.checked.discard(id(s))
        self.model.dataChanged.emit(self.model.index(0, 0),
                                    self.model.index(max(len(self.model.rows) - 1, 0), 0))

    # ---------- студенты ----------
    def add_student(self):
        if not self.pr or not self.pr.groups:
            return
        g = self.current_group()
        if g is None:
            QMessageBox.information(self, "Добавление", "Сначала выберите группу слева.")
            return
        base = g.students[-1].values if g.students else {}
        s = Student(values={k: v for k, v in base.items() if k != "name"})
        s.values["name"] = ""
        g.students.append(s)
        self.mark_dirty()
        self.reload_view(self.groups.currentRow())
        # перейти к ячейке ФИО новой строки
        src = self.model.index(next(i for i, (_, st) in enumerate(self.model.rows) if st is s), 2)
        idx = self.proxy.mapFromSource(src)
        self.table.setCurrentIndex(idx)
        self.table.scrollTo(idx)
        self.table.edit(idx)

    def delete_student(self):
        if not self.pr:
            return
        rows = sorted({self.proxy.mapToSource(i).row()
                       for i in self.table.selectionModel().selectedRows()})
        if not rows:
            return
        names = "\n".join(self.model.rows[r][1].get("name") or "‹без ФИО›" for r in rows)
        if QMessageBox.question(self, "Удаление", f"Удалить из представления:\n{names}?") \
                != QMessageBox.Yes:
            return
        for r in rows:
            g, s = self.model.rows[r]
            g.students.remove(s)
        self.mark_dirty()
        self.reload_view(self.groups.currentRow())

    # ---------- справочник ----------
    def edit_places(self, focus_place: str | None = None, import_now: bool = False):
        self.table.setFocus()
        dlg = PlacesDialog(self.places, self.pr, self.settings, self,
                           focus_place=focus_place if isinstance(focus_place, str) else None)
        if import_now:
            dlg.show()
            dlg.import_excel()
        dlg.exec()
        self.model.layoutChanged.emit()
        self.table.resizeRowsToContents()

    def table_double_clicked(self, index):
        src = self.proxy.mapToSource(index)
        if self.model.column_key(src.column()) == "_org":
            _, s = self.model.rows[src.row()]
            self.edit_places(focus_place=s.get("place"))

    # ---------- дневники ----------
    def generate(self):
        self.table.setFocus()
        rows = [(g, s) for g, s in self.model.checked_rows() if s.get("name")]
        if not rows:
            QMessageBox.information(self, "Дневники",
                                    "Отметьте галочкой студентов (первый столбец).")
            return
        dlg = GenerateDialog(rows, self.settings, self.places, self)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.options()
        if not opts.template.exists():
            QMessageBox.critical(self, "Ошибка", f"Шаблон не найден:\n{opts.template}")
            return
        progress = QProgressDialog("Создание дневников…", "Отмена", 0, len(rows), self)
        progress.setWindowModality(Qt.WindowModal)
        done, problems = [], []
        for i, (g, s) in enumerate(rows):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            try:
                r = generate_diary(s, g, opts, remove_highlight=dlg.unhl.isChecked())
                done.append(r.path)
                notes = []
                if r.missing_values:
                    notes.append("не заполнено: " + ", ".join(r.missing_values))
                if r.unknown_fields:
                    notes.append("не распознаны поля шаблона: " + "; ".join(r.unknown_fields))
                if notes:
                    problems.append(f"{s.get('name')}: " + " | ".join(notes))
            except Exception as e:  # noqa: BLE001
                problems.append(f"{s.get('name')}: ОШИБКА {e}")
        progress.setValue(len(rows))
        msg = f"Создано файлов: {len(done)}\nПапка: {opts.output_dir}"
        if problems:
            msg += "\n\nЗамечания:\n" + "\n".join(problems)
        QMessageBox.information(self, "Готово", msg)
        if done and dlg.open_after.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(opts.output_dir.resolve())))


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Дневники практики")
    w = MainWindow(argv[1] if len(argv) > 1 else None)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
