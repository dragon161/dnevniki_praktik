"""Модели данных: группы и студенты из «Представления»."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Ключи колонок таблицы представления и их подписи для интерфейса.
COLUMNS: list[tuple[str, str]] = [
    ("name", "ФИО обучающегося"),
    ("supervisor", "Руководитель от университета"),
    ("practice_type", "Вид практики"),
    ("place", "Место"),
    ("duration", "Продолжительность"),
    ("period", "Период реализации"),
    ("okved", "Вид деятельности по ЕГРЮЛ"),
]
COLUMN_TITLES = dict(COLUMNS)

# Поля шапки группы (текст до двоеточия -> ключ).
HEADER_FIELDS: list[tuple[str, str]] = [
    ("direction_code", "Код направления (специальности)"),
    ("direction_name", "Наименование направления (специальности)"),
    ("profile_code", "Код профиля (специализации)"),
    ("profile_name", "Наименование профиля (специализации)"),
    ("study_form", "Форма обучения"),
    ("faculty_line", "Факультет, кафедра, группа"),
]
HEADER_TITLES = dict(HEADER_FIELDS)


def strip_quotes(s: str) -> str:
    return s.strip().strip("«»\"' ").strip()


@dataclass
class Student:
    values: dict[str, str] = field(default_factory=dict)
    highlighted: bool = False          # ФИО было выделено цветом в исходнике
    # служебное: индекс строки (w:tr) в таблице исходного документа, None для новых
    row_index: int | None = None

    def get(self, key: str) -> str:
        return self.values.get(key, "")

    # ---- разбор ФИО ----
    @property
    def name_parts(self) -> list[str]:
        return self.get("name").split()

    @property
    def surname(self) -> str:
        p = self.name_parts
        return p[0] if p else ""

    @property
    def first_and_patronymic(self) -> str:
        return " ".join(self.name_parts[1:])

    @property
    def short_name(self) -> str:
        """«Михайлец А.Ю.»"""
        parts = self.name_parts
        if not parts:
            return ""
        initials = "".join(f"{p[0]}." for p in parts[1:]
                           if p.lower() not in ("оглы", "кызы", "улы", "уулу"))
        return f"{parts[0]} {initials}".strip()

    @property
    def gender(self) -> str | None:
        """'f' / 'm' / None — по отчеству."""
        parts = [p.lower() for p in self.name_parts]
        if not parts:
            return None
        last = parts[-1]
        if last in ("кызы", "гызы") or re.search(r"(вна|чна|шна)$", last):
            return "f"
        if last in ("оглы", "улы", "уулу") or re.search(r"(ич)$", last):
            return "m"
        return None


@dataclass
class Group:
    header: dict[str, str] = field(default_factory=dict)
    students: list[Student] = field(default_factory=list)
    # служебное: индексы элементов в документе
    table_index: int = -1
    header_par_indices: dict[str, int] = field(default_factory=dict)
    column_map: dict[str, int] = field(default_factory=dict)  # key -> grid col

    @property
    def name(self) -> str:
        line = self.header.get("faculty_line", "")
        last = line.split(",")[-1].strip() if line else ""
        return last or f"Группа {self.table_index + 1}"

    @property
    def direction(self) -> str:
        return " ".join(x for x in (self.header.get("direction_code", "").strip(),
                                    strip_quotes(self.header.get("direction_name", ""))) if x)

    @property
    def profile(self) -> str:
        return " ".join(x for x in (self.header.get("profile_code", "").strip(),
                                    strip_quotes(self.header.get("profile_name", ""))) if x)
