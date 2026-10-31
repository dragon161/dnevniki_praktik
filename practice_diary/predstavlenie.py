"""Чтение и сохранение файла «Представление» (список студентов по группам)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.oxml.ns import qn

from . import docx_utils as du
from .models import HEADER_FIELDS, Group, Student

# ключевые слова в заголовке колонки -> ключ поля
COLUMN_KEYWORDS = [
    ("name", ("фио",)),
    ("supervisor", ("руководитель",)),
    ("practice_type", ("виды учебной", "вид практики", "виды")),
    ("place", ("место",)),
    ("duration", ("продолж",)),
    ("period", ("период",)),
    ("okved", ("егрюл", "оквэд", "вид деятельности")),
]


def _detect_columns(header_tr) -> dict[str, int]:
    result: dict[str, int] = {}
    for col, tc in du.row_grid(header_tr).items():
        text = du.tc_text(tc).lower()
        for key, words in COLUMN_KEYWORDS:
            if key in result:
                continue
            if any(w in text for w in words):
                result[key] = col
                break
    return result


@dataclass
class Predstavlenie:
    path: Path
    groups: list[Group] = field(default_factory=list)

    # ---------------- загрузка ----------------
    @classmethod
    def load(cls, path: str | Path) -> "Predstavlenie":
        path = Path(path)
        document = docx.Document(str(path))
        obj = cls(path=path)
        header: dict[str, str] = {}
        header_idx: dict[str, int] = {}
        table_counter = -1
        for idx, el in enumerate(document.element.body.iterchildren()):
            if el.tag == qn("w:p"):
                text = du.paragraph_text(el).strip()
                if ":" not in text:
                    continue
                label, value = text.split(":", 1)
                for key, title in HEADER_FIELDS:
                    if label.strip().lower() == title.lower():
                        header[key] = value.strip()
                        header_idx[key] = idx
            elif el.tag == qn("w:tbl"):
                table_counter += 1
                rows = du.table_rows(el)
                if not rows:
                    continue
                hdr_i = next((i for i, tr in enumerate(rows)
                              if "фио" in " ".join(du.tc_text(tc).lower()
                                                   for tc in tr.findall(qn("w:tc")))), None)
                if hdr_i is None:
                    continue
                cols = _detect_columns(rows[hdr_i])
                if "name" not in cols:
                    continue
                g = Group(header=dict(header), table_index=table_counter,
                          header_par_indices=dict(header_idx), column_map=cols)
                for ri in range(hdr_i + 1, len(rows)):
                    values = {k: du.resolved_cell_text(rows, ri, c) for k, c in cols.items()}
                    name_tc = du.row_grid(rows[ri]).get(cols["name"])
                    hl = name_tc is not None and any(
                        du.run_is_highlighted(r, yellow_only=False) for r in name_tc.iter(qn("w:r")))
                    g.students.append(Student(values=values, highlighted=hl, row_index=ri))
                g._header_row = hdr_i  # type: ignore[attr-defined]
                obj.groups.append(g)
                header, header_idx = {}, {}
        obj.load_extra()
        return obj

    # ---------------- доп. данные (.json) ----------------
    @property
    def extra_path(self) -> Path:
        return self.path.with_suffix(".diary.json")

    def load_extra(self) -> None:
        if not self.extra_path.exists():
            return
        try:
            data = json.loads(self.extra_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        org = data.get("org_supervisor", {})
        for g in self.groups:
            for s in g.students:
                s.org_supervisor = org.get(s.key(g.name), "")

    def save_extra(self, target: Path) -> None:
        org = {s.key(g.name): s.org_supervisor
               for g in self.groups for s in g.students if s.org_supervisor}
        p = target.with_suffix(".diary.json")
        if org:
            p.write_text(json.dumps({"org_supervisor": org}, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # ---------------- сохранение ----------------
    def save(self, target: str | Path | None = None) -> Path:
        target = Path(target) if target else self.path
        document = docx.Document(str(self.path))
        body = list(document.element.body.iterchildren())
        tables = [el for el in body if el.tag == qn("w:tbl")]

        for g in self.groups:
            # шапка группы
            for key, idx in g.header_par_indices.items():
                p = body[idx]
                new = g.header.get(key, "")
                cur = du.paragraph_text(p).split(":", 1)[-1].strip()
                if new != cur:
                    du.set_text_after_colon(p, new)
            self._save_table(tables[g.table_index], g)

        document.save(str(target))
        self.save_extra(target)
        if target != self.path:
            self.path = target
        # перечитать, чтобы индексы строк соответствовали файлу
        fresh = Predstavlenie.load(target)
        org = {s.key(g.name): s.org_supervisor for g in self.groups for s in g.students}
        self.groups = fresh.groups
        for g in self.groups:
            for s in g.students:
                s.org_supervisor = org.get(s.key(g.name), s.org_supervisor)
        return target

    @staticmethod
    def _save_table(tbl, g: Group) -> None:
        rows = du.table_rows(tbl)
        hdr = getattr(g, "_header_row", 0)
        original = {ri: rows[ri] for ri in range(hdr + 1, len(rows))}
        kept = {s.row_index for s in g.students if s.row_index is not None}

        # 1. удаление строк (с переносом начала объединения на следующую строку)
        for ri in sorted(set(original) - kept, reverse=True):
            tr = original[ri]
            nxt = tr.getnext()
            if nxt is not None and nxt.tag == qn("w:tr"):
                cur_grid, next_grid = du.row_grid(tr), du.row_grid(nxt)
                for col, tc in cur_grid.items():
                    ntc = next_grid.get(col)
                    if ntc is None or du.tc_vmerge(ntc) != "continue":
                        continue
                    if du.tc_vmerge(tc) == "restart":
                        du.set_tc_vmerge(ntc, "restart")
                        for p in ntc.findall(qn("w:p")):
                            ntc.remove(p)
                        for p in tc.findall(qn("w:p")):
                            ntc.append(copy.deepcopy(p))
            tbl.remove(tr)

        # 2. новые строки — копия предыдущей строки (сохраняет оформление и нумерацию)
        ordered_trs = []
        prev_tr = None
        for s in g.students:
            if s.row_index is not None:
                tr = original[s.row_index]
            else:
                base = prev_tr if prev_tr is not None else (
                    du.table_rows(tbl)[-1] if len(du.table_rows(tbl)) > hdr + 1 else None)
                if base is None:
                    raise ValueError("Невозможно добавить строку в пустую таблицу")
                tr = copy.deepcopy(base)
                du.strip_w14(tr)
                for tc in tr.findall(qn("w:tc")):
                    if du.tc_vmerge(tc) == "restart":
                        du.set_tc_vmerge(tc, "continue")
                        du.set_tc_text(tc, "")
                anchor = prev_tr if prev_tr is not None else du.table_rows(tbl)[hdr]
                anchor.addnext(tr)
            ordered_trs.append(tr)
            prev_tr = tr

        # 3. запись значений по колонкам с учётом объединённых ячеек
        for key, col in g.column_map.items():
            desired = [s.get(key) for s in g.students]
            spans: list[list[int]] = []
            for i, tr in enumerate(ordered_trs):
                tc = du.row_grid(tr).get(col)
                if tc is None:
                    continue
                if du.tc_vmerge(tc) == "continue" and spans and spans[-1][-1] == i - 1:
                    spans[-1].append(i)
                else:
                    spans.append([i])
            for span in spans:
                tcs = [du.row_grid(ordered_trs[i]).get(col) for i in span]
                vals = [desired[i] for i in span]
                if len(set(vals)) == 1:
                    if du.tc_vmerge(tcs[0]) == "continue":  # «осиротевшее» продолжение
                        du.set_tc_vmerge(tcs[0], "restart" if len(tcs) > 1 else None)
                    if len(tcs) == 1 and du.tc_vmerge(tcs[0]) == "restart":
                        du.set_tc_vmerge(tcs[0], None)
                    if du.tc_text(tcs[0]) != vals[0]:
                        du.set_tc_text(tcs[0], vals[0])
                    continue
                # значения различаются — разбиваем объединение
                top_paras = tcs[0].findall(qn("w:p"))
                for tc, val in zip(tcs, vals):
                    if du.tc_vmerge(tc) == "continue":
                        for p in tc.findall(qn("w:p")):
                            tc.remove(p)
                        for p in top_paras[:1]:
                            np_ = copy.deepcopy(p)
                            du.strip_w14(np_)
                            tc.append(np_)
                    du.set_tc_vmerge(tc, None)
                    if du.tc_text(tc) != val:
                        du.set_tc_text(tc, val)
