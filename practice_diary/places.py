"""Справочник «Место практики → руководитель от профильной организации».

Хранится в JSON-файле в папке пользователя, поэтому руководитель, однажды
записанный для места, используется для всех студентов и всех представлений.
Справочник можно пополнять из Excel-файла (столбцы «Место …» и «Руководитель»).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_path() -> Path:
    base = os.environ.get("APPDATA")  # Windows
    root = Path(base) if base else Path.home() / ".config"
    return root / "practice_diary" / "places.json"


def _tokens(text: str) -> list[str]:
    text = (text or "").lower().replace("ё", "е")
    return re.findall(r"[0-9a-zа-я]+", text)


def normalize(text: str) -> str:
    return " ".join(_tokens(text))


@dataclass
class PlaceEntry:
    place: str
    head: str = ""


@dataclass
class PlacesBook:
    path: Path = field(default_factory=default_path)
    entries: list[PlaceEntry] = field(default_factory=list)

    # ---------------- хранение ----------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "PlacesBook":
        book = cls(path=Path(path) if path else default_path())
        if book.path.exists():
            try:
                data = json.loads(book.path.read_text(encoding="utf-8"))
                book.entries = [PlaceEntry(e.get("place", ""), e.get("head", ""))
                                for e in data.get("places", []) if e.get("place")]
            except (OSError, ValueError):
                pass
        return book

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"places": [asdict(e) for e in sorted(self.entries, key=lambda e: e.place.lower())]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---------------- изменение ----------------
    def exact(self, place: str) -> PlaceEntry | None:
        norm = normalize(place)
        return next((e for e in self.entries if normalize(e.place) == norm), None)

    def set_head(self, place: str, head: str) -> PlaceEntry:
        """Записать руководителя для места (обновит существующую запись, если она есть)."""
        place, head = place.strip(), head.strip()
        e = self.exact(place) or self.find(place)
        if e is None:
            e = PlaceEntry(place, head)
            self.entries.append(e)
        else:
            e.head = head
        return e

    def remove(self, entry: PlaceEntry) -> None:
        self.entries = [e for e in self.entries if e is not entry]

    def import_excel(self, path: str | Path) -> tuple[int, int]:
        """Добавить/обновить записи из Excel. Возвращает (добавлено, обновлено)."""
        added = updated = 0
        for place, head in read_excel(path):
            e = self.exact(place) or self.find(place)
            if e is None:
                self.entries.append(PlaceEntry(place, head))
                added += 1
            elif head and e.head != head:
                e.head = head
                updated += 1
        return added, updated

    # ---------------- поиск ----------------
    def find(self, place: str) -> PlaceEntry | None:
        """Поиск места с учётом разных кавычек, пробелов и порядка слов."""
        if not place or not self.entries:
            return None
        e = self.exact(place)
        if e:
            return e
        want = set(_tokens(place))
        if not want:
            return None
        best, best_score = None, 0.0
        for e in self.entries:
            have = set(_tokens(e.place))
            if not have:
                continue
            common = len(want & have)
            cover = common / min(len(want), len(have))
            jacc = common / len(want | have)
            score = cover * 0.7 + jacc * 0.3
            if cover >= 0.8 and jacc >= 0.5 and score > best_score:
                best, best_score = e, score
        return best

    def head_for(self, place: str) -> str:
        e = self.find(place)
        return e.head if e else ""


def read_excel(path: str | Path) -> list[tuple[str, str]]:
    """Прочитать пары (место, руководитель) из .xlsx: ищется строка-заголовок
    со столбцами «Место …» и «Руководитель …»."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            result, place_col, head_col = [], None, None
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v).strip() for v in row]
                if place_col is None:
                    low = [c.lower() for c in cells]
                    pc = next((i for i, c in enumerate(low) if "место" in c), None)
                    hc = next((i for i, c in enumerate(low) if "руковод" in c), None)
                    if pc is not None and hc is not None:
                        place_col, head_col = pc, hc
                    continue
                place = cells[place_col] if place_col < len(cells) else ""
                head = cells[head_col] if head_col < len(cells) else ""
                if place:
                    result.append((place, head))
            if result:
                return result
    finally:
        wb.close()
    raise ValueError("В файле не найдена таблица со столбцами «Место …» и «Руководитель»")
