"""Генерация дневника практики по шаблону.

В шаблоне заменяются фрагменты, выделенные ЖЁЛТЫМ цветом. Каждая непрерывная
последовательность жёлтых фрагментов внутри абзаца считается одним полем;
какое именно это поле — определяется по тексту абзаца/ячейки вокруг.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import docx
from docx.oxml.ns import qn

from . import docx_utils as du
from .models import Group, Student
from .places import PlacesBook

DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "diary_template.docx"

# Этапы рабочего графика: доли от длительности практики (начало, конец).
# Подобраны по образцу: 03.12–04.12, 04.12–05.12, 05.12–12.12, 12.12–25.12, 26.12–30.12, 30.12
STAGES = [(0, 1), (1, 2), (2, 9), (9, 22), (23, 27), (27, 27)]
STAGES_BASE = 27

# Пары «женская форма — мужская форма» для согласования текста отзыва
GENDER_WORDS = [
    ("Студентка", "Студент"), ("студентка", "студент"),
    ("прошла", "прошел"), ("Зарекомендовала", "Зарекомендовал"),
    ("Показала", "Показал"), ("относилась", "относился"),
    ("выполняла", "выполнял"), ("проявляла", "проявлял"),
    ("допускала", "допускал"), ("выполнила", "выполнил"),
    ("ознакомлена", "ознакомлен"),
]

DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def parse_period(text: str) -> tuple[date, date] | None:
    found = DATE_RE.findall(text or "")
    if len(found) < 2:
        return None
    (d1, m1, y1), (d2, m2, y2) = found[0], found[1]
    try:
        return date(int(y1), int(m1), int(d1)), date(int(y2), int(m2), int(d2))
    except ValueError:
        return None


def fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def build_schedule(start: date, end: date) -> list[tuple[date, date]]:
    total = max((end - start).days, 0)
    out = []
    for a, b in STAGES:
        sa = start + timedelta(days=round(a * total / STAGES_BASE))
        sb = start + timedelta(days=round(b * total / STAGES_BASE))
        out.append((sa, sb))
    out[-1] = (end, end)
    out[-2] = (out[-2][0], end)
    return out


def initials_first(short: str) -> str:
    """«Федорцова С.С.» -> «С.С. Федорцова»"""
    m = re.match(r"^\s*(\S+)\s+((?:[А-ЯЁA-Z]\.\s?)+)\s*$", short or "")
    if not m:
        return (short or "").strip()
    return f"{m.group(2).replace(' ', '')} {m.group(1)}"


@dataclass
class DiaryOptions:
    template: Path = DEFAULT_TEMPLATE
    output_dir: Path = Path(".")
    filename_pattern: str = "Дневник_{surname}_{group}.docx"
    gender_agreement: bool = True
    # справочник «место → руководитель от профильной организации»
    places: PlacesBook | None = None
    # перекрытие произвольных полей: {"place": "...", ...}
    overrides: dict[str, str] = field(default_factory=dict)


def student_fields(student: Student, group: Group, opts: DiaryOptions) -> dict[str, str]:
    period = parse_period(student.get("period"))
    org = opts.places.head_for(student.get("place")) if opts.places else ""
    f = {
        "surname": student.surname,
        "first_patronymic": student.first_and_patronymic,
        "short_name": student.short_name,
        "group": group.name,
        "direction": group.direction,
        "profile": group.profile,
        "place": student.get("place").replace("\n", " ").strip(),
        "period": (f"{fmt(period[0])} г. по {fmt(period[1])} г." if period
                   else student.get("period")),
        "supervisor_univ": student.get("supervisor").strip(),
        "supervisor_univ_sign": initials_first(student.get("supervisor")),
        "supervisor_org": org,
        "supervisor_org_sign": initials_first(org),
    }
    if period:
        for i, (a, b) in enumerate(build_schedule(*period)):
            f[f"stage{i + 1}"] = f"{fmt(a)} г." if a == b else f"{fmt(a)} г. – {fmt(b)} г."
    f.update({k: v for k, v in opts.overrides.items() if v})
    return f


# ---------------- поиск жёлтых полей в шаблоне ----------------

def _highlight_groups(p) -> list[list]:
    groups, cur = [], []
    for r in du.paragraph_runs(p):
        txt = du.run_text(r)
        if du.run_is_highlighted(r):
            cur.append(r)
        elif txt == "":
            continue
        else:
            if cur:
                groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _ancestor(el, tag):
    el = el.getparent()
    while el is not None and el.tag != qn(tag):
        el = el.getparent()
    return el


NAME_INITIALS_RE = re.compile(r"[А-ЯЁ][а-яё\-]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]?\.?")


def _classify(p, gi: int, text: str, para_text: str) -> str | None:
    tc = _ancestor(p, "w:tc")
    if tc is not None:
        tbl = _ancestor(tc, "w:tbl")
        rows = du.table_rows(tbl)
        header_text = " ".join(du.tc_text(c) for c in rows[0].findall(qn("w:tc"))).lower()
        tr = _ancestor(tc, "w:tr")
        if "сроки" in header_text:
            ri = rows.index(tr)
            return f"stage{ri}"
        ctext = du.tc_text(tc).lower()
        if "руководитель" in ctext and "университет" in ctext:
            return "supervisor_univ_sign"
        if "руководитель" in ctext and "организац" in ctext:
            return "supervisor_org_sign"
    t = para_text.strip().lower()
    rules = [
        ("фамилия", "surname"), ("имя", "first_patronymic"), ("группа", "group"),
        ("направление", "direction"), ("профиль", "profile"),
        ("место прохождения", "place"), ("период практики", "period"),
        ("руководитель практики от университета", "supervisor_univ"),
        ("руководитель практики от профильной", "supervisor_org"),
    ]
    for prefix, key in rules:
        if t.startswith(prefix):
            return key
    if t.startswith("студент") or "прош" in t:
        if NAME_INITIALS_RE.fullmatch(text.strip().rstrip(".")) or (gi == 0 and "предприят" not in text):
            return "short_name"
        return "place"
    return None


def _all_paragraphs(document):
    yield from document.element.body.iter(qn("w:p"))
    for s in document.sections:
        for part in (s.header, s.footer):
            if part is not None and not part.is_linked_to_previous:
                yield from part._element.iter(qn("w:p"))


def _apply_value(runs, original: str, value: str, remove_highlight: bool,
                 pad: bool = False) -> None:
    lead = original[: len(original) - len(original.lstrip())]
    trail_ws = original[len(original.rstrip()):]
    core = original.strip()
    if value and core.endswith(".") and not value.endswith("."):
        value += "."
    if pad and len(value) < len(core):
        value = value.ljust(len(core))
    du.set_run_text(runs[0], lead + value + trail_ws)
    for r in runs[1:]:
        r.getparent().remove(r)
    if remove_highlight:
        rpr = runs[0].find(qn("w:rPr"))
        if rpr is not None:
            for tag in ("w:highlight", "w:shd"):
                el = rpr.find(qn(tag))
                if el is not None:
                    rpr.remove(el)


def _apply_gender(document, gender: str) -> None:
    started = False
    for p in document.element.body.iter(qn("w:p")):
        text = du.paragraph_text(p)
        low = text.lower()
        if low.strip().startswith("отзыв"):
            started = True
            continue
        if not started:
            continue
        if low.strip().startswith("оценка результатов"):
            break
        for fem, masc in GENDER_WORDS:
            src, dst = (masc, fem) if gender == "f" else (fem, masc)
            _replace_across_runs(p, rf"(?<![А-Яа-яЁё]){src}(?![А-Яа-яЁё])", dst)


def _replace_across_runs(p, pattern: str, repl: str) -> None:
    """Замена по регулярному выражению, даже если слово разбито на несколько run."""
    while True:
        runs = du.paragraph_runs(p)
        texts = [du.run_text(r) for r in runs]
        full = "".join(texts)
        m = re.search(pattern, full)
        if not m:
            return
        start, end = m.span()
        pos = 0
        first = True
        for r, t in zip(runs, texts):
            a, b = pos, pos + len(t)
            pos = b
            if b <= start or a >= end:
                continue
            ls, le = max(start, a) - a, min(end, b) - a
            new = t[:ls] + (repl if first else "") + t[le:]
            first = False
            du.set_run_text(r, new)
        if repl and re.fullmatch(pattern, repl):  # защита от зацикливания
            return


@dataclass
class DiaryResult:
    path: Path
    unknown_fields: list[str]
    missing_values: list[str]


def generate_diary(student: Student, group: Group, opts: DiaryOptions,
                   remove_highlight: bool = False) -> DiaryResult:
    values = student_fields(student, group, opts)
    document = docx.Document(str(opts.template))
    unknown, missing = [], []
    for p in list(_all_paragraphs(document)):
        groups = _highlight_groups(p)
        if not groups:
            continue
        para_text = du.paragraph_text(p)
        for gi, runs in enumerate(groups):
            original = "".join(du.run_text(r) for r in runs)
            key = _classify(p, gi, original, para_text)
            if key is None:
                unknown.append(original.strip())
                continue
            # ячейка этапа, разбитая на 2 абзаца: «дата – » / «дата г.»
            if key.startswith("stage"):
                tc = _ancestor(p, "w:tc")
                stage_paras = [pp for pp in tc.findall(qn("w:p")) if _highlight_groups(pp)]
                if len(stage_paras) > 1:
                    v = values.get(key, "")
                    parts = v.split("– ")
                    idx = stage_paras.index(p)
                    if len(parts) == 2:
                        v = parts[0].strip() + " –" if idx == 0 else (parts[1] if idx == 1 else "")
                    elif idx > 0:
                        v = ""
                    _apply_value(runs, original, v, remove_highlight)
                    continue
            value = values.get(key)
            if not value:
                missing.append(key)
                value = "_" * 20
            _apply_value(runs, original, value, remove_highlight,
                         pad=key in ("surname", "first_patronymic"))
    if opts.gender_agreement and student.gender:
        _apply_gender(document, student.gender)

    opts.output_dir.mkdir(parents=True, exist_ok=True)
    name = opts.filename_pattern.format(
        surname=student.surname, name=student.get("name"), group=group.name,
        short_name=student.short_name)
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    if not name.lower().endswith(".docx"):
        name += ".docx"
    out = opts.output_dir / name
    document.save(str(out))
    return DiaryResult(out, unknown, sorted(set(missing)))
