#!/usr/bin/env python3
"""
xlsx_to_uat.py - Zero-dependency Excel (.xlsx) Eval inspector, importer, in-place
format-preserving workbook updater, and CSV exporter.

Uses Python standard library only (zipfile + xml.etree.ElementTree + csv + sqlite3)
so it works cleanly in restricted/offline environments without openpyxl or pandas.

Supports both SQLite DB SSOT mode (--db / --suite-id) and standalone JSON files.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_NS = {"m": _MAIN_NS}
_REL_ATTR = f"{{{_REL_NS}}}id"
_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_to_index(col: str) -> int:
    """Convert Excel column letters (e.g. 'A', 'Z', 'AA') to 0-based index."""
    idx = 0
    for ch in col.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """Read xl/sharedStrings.xml into a list of strings."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.findall(".//m:t", _NS))
        for si in root.findall("m:si", _NS)
    ]


def _list_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return list of (sheet_name, zip_entry_path) from workbook XML and relationships."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
    sheets: list[tuple[str, str]] = []
    for s in wb.findall(".//m:sheet", _NS):
        name = s.attrib["name"]
        rid = s.attrib[_REL_ATTR]
        target = rel_map[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((name, target))
    return sheets


def _extract_cell_text(cell: ET.Element, shared: list[str]) -> str:
    """Extract plain string value from an OOXML <c> element."""
    ctype = cell.attrib.get("t")
    val_el = cell.find("m:v", _NS)
    is_el = cell.find("m:is", _NS)
    if ctype == "s" and val_el is not None and val_el.text is not None:
        idx = int(val_el.text)
        return shared[idx] if 0 <= idx < len(shared) else ""
    if ctype == "inlineStr" and is_el is not None:
        return "".join(el.text or "" for el in is_el.findall(".//m:t", _NS))
    if val_el is not None and val_el.text is not None:
        return val_el.text
    return ""


def _resolve_sheet(zf: zipfile.ZipFile, sheet_name: str | None) -> tuple[str, str]:
    """Resolve sheet name to (chosen_name, zip_entry_path)."""
    sheets = _list_sheets(zf)
    if not sheets:
        raise ValueError("No sheets found in workbook.")
    if sheet_name:
        matches = [s for s in sheets if s[0] == sheet_name]
        if not matches:
            avail = ", ".join(s[0] for s in sheets)
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {avail}")
        return matches[0]
    return sheets[0]


def read_sheet_rows(
    xlsx_path: Path, sheet_name: str | None = None
) -> tuple[str, list[tuple[int, dict[str, str]]]]:
    """Read a sheet as a list of (excel_row_number, {col_letter: text}) tuples."""
    if not xlsx_path.is_file():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = _read_shared_strings(zf)
        chosen_name, target = _resolve_sheet(zf, sheet_name)
        root = ET.fromstring(zf.read(target))
        rows_out: list[tuple[int, dict[str, str]]] = []
        for row_el in root.findall(".//m:sheetData/m:row", _NS):
            rnum = int(row_el.attrib.get("r", "0"))
            row_cells: dict[str, str] = {}
            for cell in row_el.findall("m:c", _NS):
                ref = cell.attrib.get("r", "")
                m = _CELL_REF_RE.match(ref)
                if not m:
                    continue
                col_letter = m.group(1)
                txt = _extract_cell_text(cell, shared).strip()
                if txt:
                    row_cells[col_letter] = txt
            if row_cells:
                rows_out.append((rnum, row_cells))
        return chosen_name, rows_out


def inspect_workbook(xlsx_path: Path, sheet_name: str | None = None, sample_rows: int = 8) -> dict[str, Any]:
    """Return structured sheet metadata and sample rows for an .xlsx workbook."""
    if not xlsx_path.is_file():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")
    with zipfile.ZipFile(xlsx_path) as zf:
        sheets = [s[0] for s in _list_sheets(zf)]

    target_sheets = [sheet_name] if sheet_name else sheets
    details: list[dict[str, Any]] = []
    for sname in target_sheets:
        _, rows = read_sheet_rows(xlsx_path, sname)
        samples = []
        for rnum, cells in rows[:sample_rows]:
            ordered = sorted(cells.items(), key=lambda kv: _col_to_index(kv[0]))
            samples.append({"row": rnum, "cells": dict(ordered)})
        details.append({"name": sname, "non_empty_rows": len(rows), "sample_rows": samples})
    return {"file": str(xlsx_path), "sheets": sheets, "details": details}


def _resolve_col(spec: str | None, header_by_name: dict[str, str]) -> str | None:
    """Resolve a column spec (either Excel letter like 'C' or header name) to a column letter."""
    if not spec:
        return None
    cleaned = spec.strip()
    if re.fullmatch(r"[A-Za-z]{1,3}", cleaned) and cleaned.lower() not in header_by_name:
        return cleaned.upper()
    low = cleaned.lower()
    if low in header_by_name:
        return header_by_name[low]
    for h_name, col_letter in header_by_name.items():
        if low in h_name:
            return col_letter
    raise ValueError(
        f"Column '{spec}' not found. Available headers: {list(header_by_name.keys())}"
    )


def _header_map(rows: list[tuple[int, dict[str, str]]], header_row: int) -> dict[str, str]:
    """Return {lowercase_header_text: col_letter} for the specified 1-based header row."""
    for rnum, cells in rows:
        if rnum == header_row:
            return {v.strip().lower(): k for k, v in cells.items()}
    return {}


def auto_detect_mapping(xlsx_path: Path, sheet_name: str | None = None) -> dict[str, Any]:
    """Best-effort auto-detection of sheet, header row, and input/output columns."""
    chosen_sheet, rows = read_sheet_rows(xlsx_path, sheet_name)
    best_row = rows[0][0] if rows else 1
    best_score = -1
    for rnum, cells in rows[:6]:
        vals = [v.strip().lower() for v in cells.values()]
        score = 0
        for v in vals:
            if any(k in v for k in ("question", "query", "queries", "prompt")):
                score += 4
            if any(k in v for k in ("expected", "answer")):
                score += 2
            if v in ("id", "case id", "case_id", "test id", "no", "#") or v.endswith(" id"):
                score += 2
        if score > best_score:
            best_score = score
            best_row = rnum

    hmap = _header_map(rows, best_row)

    def _find_header(*candidates: str) -> str | None:
        for cand in candidates:
            for h_text in hmap:
                if cand == h_text or cand in h_text:
                    # Return original header casing from rows
                    col_l = hmap[h_text]
                    for rn, cs in rows:
                        if rn == best_row and col_l in cs:
                            return cs[col_l].strip()
        return None

    col_id = _find_header("case id", "case_id", "test id", "id")
    col_q = _find_header("queries", "question", "query", "prompt")
    col_ans = _find_header("expected answer", "expected answers", "expected output", "answer")
    col_beh = _find_header("expected behavior", "behavior", "behaviour", "rubric")
    col_src = _find_header("expected source", "expected sources", "source", "reference")
    col_rem = _find_header("remarks", "notes", "comment")

    out_ans = _find_header("actual answer", "actual answers", "response", "actual output")
    out_src = _find_header("actual source", "retrieved source", "retrieved sources")
    out_status = _find_header("status", "pass/fail", "result")
    out_comment = _find_header("review comment", "judge comment", "remarks")

    return {
        "sheet": chosen_sheet,
        "header_row": best_row,
        "group_blank_id": False,
        "columns": {
            "id": col_id,
            "question": col_q,
            "expected_answer": col_ans,
            "expected_behavior": col_beh,
            "expected_source": col_src,
            "remarks": col_rem,
        },
        "output_columns": {
            "actual_answer": out_ans,
            "actual_sources": out_src,
            "status": out_status,
            "review_comment": out_comment,
        },
    }


def parse_xlsx_cases(
    xlsx_path: Path,
    mapping: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], int]:
    """Parse .xlsx into (sheet_name, resolved_mapping, canonical_cases_list, skipped_empty_q)."""
    cfg = mapping or auto_detect_mapping(xlsx_path)
    sheet = cfg.get("sheet")
    header_row = int(cfg.get("header_row") or 1)
    cols_cfg = cfg.get("columns") or {}

    col_id_spec = cols_cfg.get("id")
    col_q_spec = cols_cfg.get("question")
    col_ans_spec = cols_cfg.get("expected_answer")
    col_beh_spec = cols_cfg.get("expected_behavior")
    col_src_spec = cols_cfg.get("expected_source")
    col_rem_spec = cols_cfg.get("remarks")
    group_blank_id = bool(cfg.get("group_blank_id", False))

    if not col_q_spec:
        raise ValueError("Missing question column. Provide columns.question or --col-question.")

    chosen_sheet, rows = read_sheet_rows(xlsx_path, sheet)
    hmap = _header_map(rows, header_row)

    col_id = _resolve_col(col_id_spec, hmap)
    col_q = _resolve_col(col_q_spec, hmap)
    col_ans = _resolve_col(col_ans_spec, hmap)
    col_beh = _resolve_col(col_beh_spec, hmap)
    col_src = _resolve_col(col_src_spec, hmap)
    col_rem = _resolve_col(col_rem_spec, hmap)

    cases_by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    last_id: str | None = None
    auto_seq = 0
    skipped_empty_q = 0

    for rnum, cells in rows:
        if rnum <= header_row:
            continue
        question = cells.get(col_q or "", "").strip()
        if not question:
            skipped_empty_q += 1
            continue

        raw_id = cells.get(col_id or "", "").strip() if col_id else ""
        if raw_id:
            case_id = raw_id
            last_id = case_id
        elif group_blank_id and last_id:
            case_id = last_id
        else:
            auto_seq += 1
            case_id = f"EVAL-{auto_seq:03d}"
            last_id = case_id

        expected_answer = cells.get(col_ans or "", "").strip() if col_ans else ""
        beh_parts: list[str] = []
        if col_beh and cells.get(col_beh):
            beh_parts.append(cells[col_beh].strip())
        if col_src and cells.get(col_src):
            beh_parts.append(f"Expected source: {cells[col_src].strip()}")
        if col_rem and cells.get(col_rem):
            beh_parts.append(f"Remarks: {cells[col_rem].strip()}")
        expected_behavior = " | ".join(beh_parts)

        turn_obj = {
            "question": question,
            "expected_answer": expected_answer,
            "expected_behavior": expected_behavior,
        }
        if case_id not in cases_by_id:
            cases_by_id[case_id] = {"id": case_id, "turns": []}
            ordered_ids.append(case_id)
        cases_by_id[case_id]["turns"].append(turn_obj)

    output_list = [cases_by_id[cid] for cid in ordered_ids]
    resolved_cfg = {
        "sheet": chosen_sheet,
        "header_row": header_row,
        "group_blank_id": group_blank_id,
        "columns": cols_cfg,
        "output_columns": cfg.get("output_columns") or {},
    }
    return chosen_sheet, resolved_cfg, output_list, skipped_empty_q


def update_xlsx_from_records(
    template_path: Path,
    results_data: list[dict[str, Any]],
    output_path: Path,
    mapping: dict[str, Any],
) -> tuple[str, int]:
    """Write result records back into a copy of template .xlsx preserving all styles/formatting."""
    if not template_path.is_file():
        raise FileNotFoundError(f"Template Excel file not found: {template_path}")

    sheet = mapping.get("sheet")
    header_row = int(mapping.get("header_row") or 1)
    cols_cfg = mapping.get("columns") or {}
    out_cfg = mapping.get("output_columns") or {}
    group_blank_id = bool(mapping.get("group_blank_id", False))

    col_id_spec = cols_cfg.get("id")
    col_q_spec = cols_cfg.get("question")
    out_ans_spec = out_cfg.get("actual_answer")
    out_src_spec = out_cfg.get("actual_sources")
    out_status_spec = out_cfg.get("status")
    out_comment_spec = out_cfg.get("review_comment")

    if not any([out_ans_spec, out_src_spec, out_status_spec, out_comment_spec]):
        raise ValueError(
            "Specify at least one output column via mapping output_columns or CLI flags."
        )

    turn_lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for rec in results_data:
        cid = str(rec.get("id", "")).strip()
        for idx, tr in enumerate(rec.get("turns") or [], 1):
            t_num = int(tr.get("turn", idx))
            turn_lookup[(cid, t_num)] = tr

    chosen_sheet, rows = read_sheet_rows(template_path, sheet)
    hmap = _header_map(rows, header_row)

    col_id = _resolve_col(col_id_spec, hmap)
    col_q = _resolve_col(col_q_spec, hmap)
    out_ans = _resolve_col(out_ans_spec, hmap)
    out_src = _resolve_col(out_src_spec, hmap)
    out_status = _resolve_col(out_status_spec, hmap)
    out_comment = _resolve_col(out_comment_spec, hmap)

    row_to_turn: dict[int, dict[str, Any]] = {}
    turn_counts: dict[str, int] = {}
    last_id: str | None = None
    auto_seq = 0

    for rnum, cells in rows:
        if rnum <= header_row:
            continue
        if col_q and not cells.get(col_q, "").strip():
            continue
        raw_id = cells.get(col_id or "", "").strip() if col_id else ""
        if raw_id:
            case_id = raw_id
            last_id = case_id
        elif group_blank_id and last_id:
            case_id = last_id
        else:
            auto_seq += 1
            case_id = f"EVAL-{auto_seq:03d}"
            last_id = case_id

        turn_counts[case_id] = turn_counts.get(case_id, 0) + 1
        key = (case_id, turn_counts[case_id])
        if key in turn_lookup:
            row_to_turn[rnum] = turn_lookup[key]

    ET.register_namespace("", _MAIN_NS)
    ET.register_namespace("r", _REL_NS)

    same_file = template_path.resolve() == output_path.resolve()
    write_target = output_path.with_suffix(".tmp.xlsx") if same_file else output_path
    write_target.parent.mkdir(parents=True, exist_ok=True)

    updated_rows = 0
    with zipfile.ZipFile(template_path, "r") as zin:
        _, target_xml_path = _resolve_sheet(zin, chosen_sheet)
        sheet_root = ET.fromstring(zin.read(target_xml_path))

        col_styles: dict[str, str] = {}
        for row_el in sheet_root.findall(".//m:sheetData/m:row", _NS):
            rnum = int(row_el.attrib.get("r", "0"))
            if rnum <= header_row:
                continue
            for cell in row_el.findall("m:c", _NS):
                m = _CELL_REF_RE.match(cell.attrib.get("r", ""))
                if m and "s" in cell.attrib and m.group(1) not in col_styles:
                    col_styles[m.group(1)] = cell.attrib["s"]

        for row_el in sheet_root.findall(".//m:sheetData/m:row", _NS):
            rnum = int(row_el.attrib.get("r", "0"))
            tr = row_to_turn.get(rnum)
            if not tr:
                continue

            raw = tr.get("raw_response") or {}
            rev = tr.get("uat_review") or tr.get("eval_review") or {}
            answer_text = raw.get("text", "") or raw.get("error", "")
            sources_text = "; ".join(str(s) for s in (raw.get("sources") or []))
            status_text = str(rev.get("status", ""))
            comment_text = str(rev.get("comment", ""))
            if not out_status and status_text and comment_text:
                comment_text = f"[{status_text} ({rev.get('score', '')})] {comment_text}"

            if out_ans:
                _set_inline_cell(row_el, rnum, out_ans, answer_text, col_styles.get(out_ans))
            if out_src and sources_text:
                _set_inline_cell(row_el, rnum, out_src, sources_text, col_styles.get(out_src))
            if out_status:
                _set_inline_cell(row_el, rnum, out_status, status_text, col_styles.get(out_status))
            if out_comment and comment_text:
                _set_inline_cell(row_el, rnum, out_comment, comment_text, col_styles.get(out_comment))
            updated_rows += 1

        patched_xml = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(write_target, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == target_xml_path:
                    zout.writestr(item, patched_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

    if same_file:
        write_target.replace(output_path)

    return chosen_sheet, updated_rows


def export_records_to_csv(results_data: list[dict[str, Any]], output_path: Path) -> int:
    """Export canonical eval results list to UTF-8-BOM CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ID",
                "Turn",
                "Question",
                "Actual Answer",
                "Retrieved Sources",
                "Status",
                "Score",
                "Behavior Check",
                "Answer Check",
                "Review Comment",
            ]
        )
        for rec in results_data:
            cid = rec.get("id", "")
            for tr in rec.get("turns") or []:
                raw = tr.get("raw_response") or {}
                rev = tr.get("uat_review") or tr.get("eval_review") or {}
                src_str = "; ".join(str(s) for s in (raw.get("sources") or []))
                writer.writerow(
                    [
                        cid,
                        tr.get("turn", 1),
                        tr.get("question", ""),
                        raw.get("text", "") or raw.get("error", ""),
                        src_str,
                        rev.get("status", ""),
                        rev.get("score", ""),
                        rev.get("behavior_check", ""),
                        rev.get("answer_check", ""),
                        rev.get("comment", ""),
                    ]
                )
                row_count += 1
    return row_count


def _set_inline_cell(
    row_el: ET.Element,
    rnum: int,
    col_letter: str,
    text: str,
    fallback_style: str | None = None,
) -> None:
    """Write an inlineStr cell into an OOXML <row>, preserving style and column order."""
    target_ref = f"{col_letter}{rnum}"
    target_idx = _col_to_index(col_letter)

    existing: ET.Element | None = None
    insert_pos = len(row_el)
    for pos, cell in enumerate(list(row_el)):
        m = _CELL_REF_RE.match(cell.attrib.get("r", ""))
        if not m:
            continue
        c_idx = _col_to_index(m.group(1))
        if c_idx == target_idx:
            existing = cell
            break
        if c_idx > target_idx:
            insert_pos = pos
            break

    if existing is None:
        cell = ET.Element(f"{{{_MAIN_NS}}}c", {"r": target_ref, "t": "inlineStr"})
        if fallback_style:
            cell.attrib["s"] = fallback_style
        row_el.insert(insert_pos, cell)
    else:
        cell = existing
        style = cell.attrib.get("s")
        cell.attrib.clear()
        cell.attrib["r"] = target_ref
        if style:
            cell.attrib["s"] = style
        cell.attrib["t"] = "inlineStr"
        for child in list(cell):
            cell.remove(child)

    is_el = ET.SubElement(cell, f"{{{_MAIN_NS}}}is")
    t_el = ET.SubElement(is_el, f"{{{_MAIN_NS}}}t")
    if text.startswith(" ") or text.endswith(" ") or "\n" in text:
        t_el.attrib[_XML_SPACE] = "preserve"
    t_el.text = text


def _open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _load_db_results(db_path: Path, suite_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conn = _open_db(db_path)
    try:
        srow = conn.execute(
            "SELECT excel_mapping_json FROM eval_suites WHERE id = ?",
            (suite_id,),
        ).fetchone()
        if not srow:
            raise KeyError(f"Eval suite not found in DB: {suite_id}")
        mapping = json.loads(srow["excel_mapping_json"] or "{}")

        rows = conn.execute(
            """
            SELECT c.case_id, c.turns_json, r.status, r.score, r.comment, r.result_json
            FROM eval_cases c
            LEFT JOIN eval_latest_results r
                ON r.suite_id = c.suite_id AND r.case_id = c.case_id
            WHERE c.suite_id = ?
            ORDER BY c.sort_order ASC, c.case_id ASC
            """,
            (suite_id,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            res_obj = json.loads(row["result_json"]) if row["result_json"] else None
            if res_obj and isinstance(res_obj.get("turns"), list):
                results.append(res_obj)
            else:
                case_turns = json.loads(row["turns_json"] or "[]")
                results.append(
                    {
                        "id": row["case_id"],
                        "uat_review": {
                            "status": row["status"] or "PENDING",
                            "score": float(row["score"] or 0.0),
                            "comment": row["comment"] or "",
                        },
                        "turns": [
                            {
                                "turn": idx,
                                "question": ct.get("question", ""),
                                "expected_answer": ct.get("expected_answer", ""),
                                "expected_behavior": ct.get("expected_behavior", ""),
                                "raw_response": {},
                                "uat_review": {},
                            }
                            for idx, ct in enumerate(case_turns, 1)
                        ],
                    }
                )
        return mapping, results
    finally:
        conn.close()


def _import_cases_to_db(
    db_path: Path,
    *,
    project_id: str,
    env: str,
    suite_name: str,
    suite_id: str | None,
    cases: list[dict[str, Any]],
    mapping: dict[str, Any],
    source_xlsx_name: str,
) -> str:
    now = time.time()
    conn = _open_db(db_path)
    try:
        slug = re.sub(r"[^a-z0-9]+", "-", suite_name.lower()).strip("-") or "suite"
        target_id = suite_id or f"{project_id}__{env}__{slug}"
        existing = conn.execute("SELECT id FROM eval_suites WHERE id = ?", (target_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE eval_suites
                SET name = ?, excel_mapping_json = ?, source_xlsx_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (suite_name, json.dumps(mapping, ensure_ascii=False), source_xlsx_name, now, target_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO eval_suites(
                    id, project_id, env, slug, name, description,
                    config_json, rubric_md, excel_mapping_json, source_xlsx_name,
                    is_default, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '', '{}', '', ?, ?, 0, ?, ?)
                """,
                (
                    target_id,
                    project_id,
                    env,
                    slug,
                    suite_name,
                    json.dumps(mapping, ensure_ascii=False),
                    source_xlsx_name,
                    now,
                    now,
                ),
            )
        for idx, item in enumerate(cases):
            cid = str(item["id"])
            turns = item.get("turns") or []
            first_q = turns[0]["question"] if turns else ""
            conn.execute(
                """
                INSERT INTO eval_cases(
                    suite_id, case_id, sort_order, first_question, turn_count, turns_json, tags_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?)
                ON CONFLICT(suite_id, case_id) DO UPDATE SET
                    sort_order = excluded.sort_order,
                    first_question = excluded.first_question,
                    turn_count = excluded.turn_count,
                    turns_json = excluded.turns_json,
                    updated_at = excluded.updated_at
                """,
                (target_id, cid, idx, first_q, len(turns), json.dumps(turns, ensure_ascii=False), now),
            )
        conn.commit()
        return target_id
    finally:
        conn.close()


def cmd_inspect(args: argparse.Namespace) -> None:
    """Inspect an Excel workbook and print sheets and sample rows."""
    info = inspect_workbook(args.file, sheet_name=args.sheet, sample_rows=args.rows)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return

    print(f"Workbook: {info['file']}")
    print(f"Sheets ({len(info['sheets'])}): {info['sheets']}")
    for d in info["details"]:
        print(f"\n--- Sheet: {d['name']} ({d['non_empty_rows']} non-empty rows) ---")
        for sr in d["sample_rows"]:
            preview = [
                f"{col}={val.replace(chr(10), ' ')[:55]}"
                for col, val in list(sr["cells"].items())[:12]
            ]
            print(f"  Row {sr['row']}: {preview}")


def _build_mapping_from_args(args: argparse.Namespace, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = dict(fallback or {})
    if getattr(args, "mapping", None):
        if not args.mapping.is_file():
            raise FileNotFoundError(f"Mapping file not found: {args.mapping}")
        cfg = json.loads(args.mapping.read_text(encoding="utf-8"))

    cols = dict(cfg.get("columns") or {})
    out_cols = dict(cfg.get("output_columns") or {})
    if getattr(args, "col_id", None):
        cols["id"] = args.col_id
    if getattr(args, "col_question", None):
        cols["question"] = args.col_question
    if getattr(args, "col_expected_answer", None):
        cols["expected_answer"] = args.col_expected_answer
    if getattr(args, "col_expected_behavior", None):
        cols["expected_behavior"] = args.col_expected_behavior
    if getattr(args, "col_expected_source", None):
        cols["expected_source"] = args.col_expected_source
    if getattr(args, "col_remarks", None):
        cols["remarks"] = args.col_remarks

    if getattr(args, "col_actual_answer", None):
        out_cols["actual_answer"] = args.col_actual_answer
    if getattr(args, "col_actual_sources", None):
        out_cols["actual_sources"] = args.col_actual_sources
    if getattr(args, "col_status", None):
        out_cols["status"] = args.col_status
    if getattr(args, "col_review_comment", None):
        out_cols["review_comment"] = args.col_review_comment

    return {
        "sheet": getattr(args, "sheet", None) or cfg.get("sheet"),
        "header_row": args.header_row if getattr(args, "header_row", None) is not None else int(cfg.get("header_row") or 1),
        "group_blank_id": bool(getattr(args, "group_blank_id", False) or cfg.get("group_blank_id", False)),
        "columns": cols,
        "output_columns": out_cols,
    }


def cmd_import(args: argparse.Namespace) -> None:
    """Import an Excel eval sheet into SQLite DB (--db) or legacy JSON (-o)."""
    base_cfg = (
        None
        if (args.mapping or args.col_question)
        else auto_detect_mapping(args.file, sheet_name=args.sheet)
    )
    cfg = _build_mapping_from_args(args, fallback=base_cfg)
    chosen_sheet, resolved_cfg, output_list, skipped_empty_q = parse_xlsx_cases(args.file, cfg)
    total_turns = sum(len(c["turns"]) for c in output_list)

    if args.db:
        if not args.project or not args.env:
            raise ValueError("DB import requires --project and --env.")
        sname = args.suite_name or args.file.stem
        sid = _import_cases_to_db(
            args.db,
            project_id=args.project,
            env=args.env,
            suite_name=sname,
            suite_id=args.suite_id,
            cases=output_list,
            mapping=resolved_cfg,
            source_xlsx_name=args.file.name,
        )
        print(
            f"Imported {len(output_list)} case(s) ({total_turns} turn(s)) from '{chosen_sheet}' "
            f"(skipped {skipped_empty_q} empty rows) -> SQLite suite '{sid}'"
        )
        return

    if not args.output:
        raise ValueError("Provide either --db or -o/--output JSON path.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_list, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Imported {len(output_list)} conversation(s) ({total_turns} turn(s)) "
        f"from '{chosen_sheet}' (skipped {skipped_empty_q} row(s) with empty question) -> {args.output}"
    )


def cmd_update_xlsx(args: argparse.Namespace) -> None:
    """Write eval results from DB (--db + --suite-id) or JSON back into a copy of original .xlsx."""
    db_mapping: dict[str, Any] = {}
    if args.db and args.suite_id:
        db_mapping, results_data = _load_db_results(args.db, args.suite_id)
    elif args.results:
        if not args.results.is_file():
            raise FileNotFoundError(f"Results JSON not found: {args.results}")
        results_data = json.loads(args.results.read_text(encoding="utf-8"))
        if not isinstance(results_data, list):
            raise ValueError("Results JSON must be a list of conversation records.")
    else:
        raise ValueError("Provide either (--db and --suite-id) or a results JSON path.")

    cfg = _build_mapping_from_args(args, fallback=db_mapping)
    chosen_sheet, updated_rows = update_xlsx_from_records(args.template, results_data, args.output, cfg)
    print(f"Updated {updated_rows} row(s) in '{chosen_sheet}' (formatting preserved) -> {args.output}")


def cmd_export(args: argparse.Namespace) -> None:
    """Export eval results from DB (--db + --suite-id) or JSON to UTF-8-BOM CSV."""
    if args.db and args.suite_id:
        _, data = _load_db_results(args.db, args.suite_id)
    elif args.results:
        if not args.results.is_file():
            raise FileNotFoundError(f"Results file not found: {args.results}")
        data = json.loads(args.results.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Results JSON must be a list of conversation records.")
    else:
        raise ValueError("Provide either (--db and --suite-id) or a results JSON path.")

    row_count = export_records_to_csv(data, args.output)
    print(f"Exported {row_count} turn row(s) -> {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-dependency Excel (.xlsx) Eval inspector, DB/JSON importer, updater, and CSV exporter."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser("inspect", help="Inspect sheets, headers, and sample rows of an .xlsx file")
    p_ins.add_argument("file", type=Path, help="Path to .xlsx workbook")
    p_ins.add_argument("--sheet", type=str, default=None, help="Inspect only this sheet name")
    p_ins.add_argument("--rows", type=int, default=8, help="Sample rows per sheet (default: 8)")
    p_ins.add_argument("--json", action="store_true", help="Output inspection result as JSON")
    p_ins.set_defaults(func=cmd_inspect)

    p_imp = sub.add_parser("import", help="Import an Excel eval sheet into SQLite DB or JSON")
    p_imp.add_argument("file", type=Path, help="Path to .xlsx workbook")
    p_imp.add_argument("-o", "--output", type=Path, default=None, help="Output JSON path (legacy mode)")
    p_imp.add_argument("--db", type=Path, default=None, help="SQLite DB path (ask_workbench.db)")
    p_imp.add_argument("--project", type=str, default=None, help="Project ID when importing to --db")
    p_imp.add_argument("--env", type=str, default=None, choices=["sbx", "dev", "uat", "prod"], help="Environment when importing to --db")
    p_imp.add_argument("--suite-id", type=str, default=None, help="Optional suite ID override for --db")
    p_imp.add_argument("--suite-name", type=str, default=None, help="Suite display name for --db")
    p_imp.add_argument("--mapping", type=Path, default=None, help="Path to excel_mapping.json")
    p_imp.add_argument("--sheet", type=str, default=None, help="Sheet name (default: first sheet)")
    p_imp.add_argument("--header-row", type=int, default=None, help="1-based Excel header row number")
    p_imp.add_argument("--col-id", type=str, default=None, help="ID column letter or header name")
    p_imp.add_argument("--col-question", type=str, default=None, help="Question column letter or header name")
    p_imp.add_argument("--col-expected-answer", type=str, default=None, help="Expected answer column")
    p_imp.add_argument("--col-expected-behavior", type=str, default=None, help="Expected behavior column")
    p_imp.add_argument("--col-expected-source", type=str, default=None, help="Expected source/citation column")
    p_imp.add_argument("--col-remarks", type=str, default=None, help="Remarks/notes column")
    p_imp.add_argument("--group-blank-id", action="store_true", help="Attach rows with blank ID as follow-up turns")
    p_imp.set_defaults(func=cmd_import)

    p_upd = sub.add_parser("update-xlsx", help="Write eval results back into a copy of the original .xlsx")
    p_upd.add_argument("template", type=Path, help="Original input .xlsx workbook")
    p_upd.add_argument("results", type=Path, nargs="?", default=None, help="Results JSON path (if not using --db)")
    p_upd.add_argument("-o", "--output", type=Path, required=True, help="Output .xlsx path")
    p_upd.add_argument("--db", type=Path, default=None, help="SQLite DB path (ask_workbench.db)")
    p_upd.add_argument("--suite-id", type=str, default=None, help="Eval suite ID in --db")
    p_upd.add_argument("--mapping", type=Path, default=None, help="Path to excel_mapping.json")
    p_upd.add_argument("--sheet", type=str, default=None, help="Sheet name")
    p_upd.add_argument("--header-row", type=int, default=None, help="1-based header row number")
    p_upd.add_argument("--col-id", type=str, default=None, help="ID column letter or header name")
    p_upd.add_argument("--col-question", type=str, default=None, help="Question column")
    p_upd.add_argument("--col-actual-answer", type=str, default=None, help="Target column for actual answer")
    p_upd.add_argument("--col-actual-sources", type=str, default=None, help="Target column for retrieved sources")
    p_upd.add_argument("--col-status", type=str, default=None, help="Target column for status")
    p_upd.add_argument("--col-review-comment", type=str, default=None, help="Target column for judge review comment")
    p_upd.add_argument("--group-blank-id", action="store_true", help="Match blank-ID follow-up rows to previous ID")
    p_upd.set_defaults(func=cmd_update_xlsx)

    p_exp = sub.add_parser("export", help="Export eval results from DB or JSON to UTF-8-BOM CSV")
    p_exp.add_argument("results", type=Path, nargs="?", default=None, help="Results JSON path (if not using --db)")
    p_exp.add_argument("--db", type=Path, default=None, help="SQLite DB path (ask_workbench.db)")
    p_exp.add_argument("--suite-id", type=str, default=None, help="Eval suite ID in --db")
    p_exp.add_argument("-o", "--output", type=Path, required=True, help="Output .csv path")
    p_exp.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
