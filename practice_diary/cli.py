"""Командная строка.

    python -m practice_diary.cli show  Представление.docx
    python -m practice_diary.cli diary Представление.docx -s "Михайлец" -s "Асеев" -o out/
    python -m practice_diary.cli diary Представление.docx --group МЕНОZ-631 -o out/
    python -m practice_diary.cli set   Представление.docx "Михайлец" place "ООО «Ромашка»"

Справочник руководителей по местам практики:
    python -m practice_diary.cli places list
    python -m practice_diary.cli places import Руководители.xlsx
    python -m practice_diary.cli places set "ООО «Ромашка»" "Иванов И.И."
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .diary import DEFAULT_TEMPLATE, DiaryOptions, generate_diary
from .models import COLUMN_TITLES, COLUMNS, HEADER_FIELDS
from .places import PlacesBook
from .predstavlenie import Predstavlenie


def _find(pr: Predstavlenie, query: str, group: str | None = None):
    q = query.lower().strip()
    res = []
    for g in pr.groups:
        if group and g.name.lower() != group.lower():
            continue
        for s in g.students:
            if q and q in s.get("name").lower():
                res.append((g, s))
    return res


def cmd_show(a) -> int:
    pr = Predstavlenie.load(a.file)
    for g in pr.groups:
        print(f"\n=== {g.name}  ({len(g.students)} чел.) ===")
        for key, title in HEADER_FIELDS:
            if g.header.get(key):
                print(f"  {title}: {g.header[key]}")
        for i, s in enumerate(g.students, 1):
            mark = " *" if s.highlighted else ""
            name = s.get("name") or "<ФИО не заполнено>"
            print(f"  {i:>2}. {name}{mark}")
            if a.full:
                for key, title in COLUMNS[1:]:
                    print(f"        {title}: {s.get(key).replace(chr(10), ' ')}")
    return 0


def cmd_set(a) -> int:
    pr = Predstavlenie.load(a.file)
    found = _find(pr, a.student, a.group)
    if len(found) != 1:
        print(f"Найдено студентов: {len(found)} — уточните запрос", file=sys.stderr)
        return 1
    g, s = found[0]
    if a.field in COLUMN_TITLES:
        s.values[a.field] = a.value
    else:
        print(f"Неизвестное поле. Доступно: {', '.join(COLUMN_TITLES)}",
              file=sys.stderr)
        return 1
    out = pr.save(a.output or a.file)
    print(f"Сохранено: {out}")
    return 0


def cmd_diary(a) -> int:
    pr = Predstavlenie.load(a.file)
    targets = []
    if a.student:
        for q in a.student:
            f = _find(pr, q, a.group)
            if not f:
                print(f"Не найден: {q}", file=sys.stderr)
            targets.extend(f)
    elif a.group:
        targets = [(g, s) for g in pr.groups if g.name.lower() == a.group.lower()
                   for s in g.students if s.get("name")]
    else:
        print("Укажите --student или --group", file=sys.stderr)
        return 1
    opts = DiaryOptions(template=Path(a.template), output_dir=Path(a.output),
                        places=PlacesBook.load(),
                        gender_agreement=not a.no_gender)
    for g, s in targets:
        r = generate_diary(s, g, opts, remove_highlight=a.remove_highlight)
        print(f"✔ {r.path}")
        if r.missing_values:
            print(f"   не заполнено: {', '.join(r.missing_values)}")
        if r.unknown_fields:
            print(f"   нераспознанные жёлтые поля: {r.unknown_fields}")
    return 0


def cmd_places(a) -> int:
    book = PlacesBook.load()
    if a.action == "import":
        added, updated = book.import_excel(a.args[0])
        book.save()
        print(f"Добавлено мест: {added}, обновлено руководителей: {updated}")
    elif a.action == "set":
        if len(a.args) != 2:
            print('Использование: places set "Место" "Руководитель"', file=sys.stderr)
            return 1
        book.set_head(*a.args)
        book.save()
        print("Сохранено")
    else:
        for e in sorted(book.entries, key=lambda e: e.place.lower()):
            print(f"{e.place}  →  {e.head or '—'}")
    print(f"(справочник: {book.path})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="practice_diary")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("show", help="показать содержимое представления")
    p.add_argument("file")
    p.add_argument("--full", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("set", help="изменить поле студента и сохранить файл")
    p.add_argument("file")
    p.add_argument("student")
    p.add_argument("field")
    p.add_argument("value")
    p.add_argument("--group")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("diary", help="создать дневники")
    p.add_argument("file")
    p.add_argument("-s", "--student", action="append", help="часть ФИО (можно несколько)")
    p.add_argument("-g", "--group")
    p.add_argument("-o", "--output", default="diaries")
    p.add_argument("-t", "--template", default=str(DEFAULT_TEMPLATE))
    p.add_argument("--no-gender", action="store_true", help="не согласовывать род в отзыве")
    p.add_argument("--remove-highlight", action="store_true", help="убрать жёлтое выделение")
    p.set_defaults(func=cmd_diary)

    p = sub.add_parser("places", help="справочник руководителей по местам практики")
    p.add_argument("action", choices=["list", "import", "set"])
    p.add_argument("args", nargs="*")
    p.set_defaults(func=cmd_places)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
