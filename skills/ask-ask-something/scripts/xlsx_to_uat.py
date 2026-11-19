#!/usr/bin/env python3
"""
xlsx_to_uat.py - Zero-dependency Excel (.xlsx) UAT inspector, importer, and CSV exporter.

Uses Python standard library only (zipfile + xml.etree.ElementTree + csv) so it works
in restricted/offline environments without openpyxl or pandas.

Subcommands:
  inspect <file.xlsx>                 Print sheets, detected headers, and sample rows.
  import  <file.xlsx> -o <out.json>   Convert an Excel UAT sheet to uat_questions.json.
  export  <res.json>  -o <out.csv>    Export uat_results.json to UTF-8-BOM CSV for Excel.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
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


def read_sheet_rows(xlsx_path: Path, sheet_name: str | None = None) -> tuple[str, list[tuple[int, dict[str, str]]]]:
    """Read a sheet as a list of (excel_row_number, {col_letter: text}) tuples."""
    if not xlsx_path.is_file():
        raise FileNotFoundError(f"Excel file not found: {xlsx_path}")
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = _read_shared_strings(zf)
        sheets = _list_sheets(zf)
        if not sheets:
            raise ValueError(f"No sheets found in {xlsx_path}")
        if sheet_name:
            matches = [s for s in sheets if s[0] == sheet_name]
            if not matches:
                avail = ", ".join(s[0] for s in sheets)
                raise ValueError(f"Sheet '{sheet_name}' not found. Available: {avail}")
            chosen_name, target = matches[0]
        else:
            chosen_name, target = sheets[0]

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


def cmd_inspect(args: argparse.Namespace) -> None:
    """Inspect an Excel workbook and print sheets and sample rows."""
    xlsx_path: Path = args.file
    with zipfile.ZipFile(xlsx_path) as zf:
        sheets = _list_sheets(zf)

    print(f"Workbook: {xlsx_path}")
    print(f"Sheets ({len(sheets)}): {[s[0] for s in sheets]}")

    target_sheets = [args.sheet] if args.sheet else [s[0] for s in sheets]
    for sname in target_sheets:
        _, rows = read_sheet_rows(xlsx_path, sname)
        print(f"\n--- Sheet: {sname} ({len(rows)} non-empty rows) ---")
        for rnum, cells in rows[: args.rows]:
            ordered = sorted(cells.items(), key=lambda kv: _col_to_index(kv[0]))[:12]
            preview = [f"{col}={val.replace(chr(10), ' ')[:55]}" for col, val in ordered]
            print(f"  Row {rnum}: {preview}")


def _resolve_col(spec: str | None, header_by_name: dict[str, str]) -> str | None:
    """Resolve a column spec (either Excel letter like 'C' or header name) to a column letter."""
    if not spec:
        return None
    cleaned = spec.strip()
    if re.fullmatch(r"[A-Za-z]{1,3}", cleaned):
        upper = cleaned.upper()
        # Only treat as literal letter if it does not exactly match a header name
        if cleaned.lower() not in header_by_name:
            return upper
    low = cleaned.lower()
    if low in header_by_name:
        return header_by_name[low]
    # Substring fallback for long/multiline Excel headers
    for h_name, col_letter in header_by_name.items():
        if low in h_name:
            return col_letter
    raise ValueError(
        f"Column '{spec}' not found. Available headers: {list(header_by_name.keys())}"
    )


def cmd_import(args: argparse.Namespace) -> None:
    """Convert an Excel UAT sheet into canonical uat_questions.json."""
    cfg: dict[str, Any] = {}
    if args.mapping:
        if not args.mapping.is_file():
            raise FileNotFoundError(f"Mapping file not found: {args.mapping}")
        cfg = json.loads(args.mapping.read_text(encoding="utf-8"))

    sheet = args.sheet or cfg.get("sheet")
    header_row = args.header_row if args.header_row is not None else int(cfg.get("header_row", 1))
    cols_cfg = cfg.get("columns") or {}

    col_id_spec = args.col_id or cols_cfg.get("id")
    col_q_spec = args.col_question or cols_cfg.get("question")
    col_ans_spec = args.col_expected_answer or cols_cfg.get("expected_answer")
    col_beh_spec = args.col_expected_behavior or cols_cfg.get("expected_behavior")
    col_src_spec = args.col_expected_source or cols_cfg.get("expected_source")
    col_rem_spec = args.col_remarks or cols_cfg.get("remarks")
    group_blank_id = args.group_blank_id or bool(cfg.get("group_blank_id", False))

    if not col_q_spec:
        raise ValueError("Missing question column. Provide --col-question or columns.question in --mapping.")

    chosen_sheet, rows = read_sheet_rows(args.file, sheet)

    header_cells: dict[str, str] = {}
    for rnum, cells in rows:
        if rnum == header_row:
            header_cells = cells
            break
    header_by_name = {v.strip().lower(): k for k, v in header_cells.items()}

    col_id = _resolve_col(col_id_spec, header_by_name)
    col_q = _resolve_col(col_q_spec, header_by_name)
    col_ans = _resolve_col(col_ans_spec, header_by_name)
    col_beh = _resolve_col(col_beh_spec, header_by_name)
    col_src = _resolve_col(col_src_spec, header_by_name)
    col_rem = _resolve_col(col_rem_spec, header_by_name)

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
            case_id = f"UAT-{auto_seq:03d}"
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
    total_turns = sum(len(c["turns"]) for c in output_list)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Imported {len(output_list)} conversation(s) ({total_turns} turn(s)) "
        f"from '{chosen_sheet}' (skipped {skipped_empty_q} row(s) with empty question) -> {args.output}"
    )


def cmd_export(args: argparse.Namespace) -> None:
    """Export uat_results.json to a UTF-8-BOM CSV file ready for Excel sign-off."""
    if not args.results.is_file():
        raise FileNotFoundError(f"Results file not found: {args.results}")
    data = json.loads(args.results.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Results JSON must be a list of conversation records.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
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
        for rec in data:
            cid = rec.get("id", "")
            for tr in rec.get("turns") or []:
                raw = tr.get("raw_response") or {}
                rev = tr.get("uat_review") or {}
                sources = raw.get("sources") or []
                src_str = "; ".join(str(s) for s in sources)
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
    print(f"Exported {row_count} turn row(s) -> {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-dependency Excel (.xlsx) UAT inspector, importer, and CSV exporter."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser("inspect", help="Inspect sheets, headers, and sample rows of an .xlsx file")
    p_ins.add_argument("file", type=Path, help="Path to .xlsx workbook")
    p_ins.add_argument("--sheet", type=str, default=None, help="Inspect only this sheet name")
    p_ins.add_argument("--rows", type=int, default=8, help="Sample rows per sheet (default: 8)")
    p_ins.set_defaults(func=cmd_inspect)

    p_imp = sub.add_parser("import", help="Convert an Excel UAT sheet into uat_questions.json")
    p_imp.add_argument("file", type=Path, help="Path to .xlsx workbook")
    p_imp.add_argument("-o", "--output", type=Path, required=True, help="Output uat_questions.json path")
    p_imp.add_argument("--mapping", type=Path, default=None, help="Path to excel_mapping.json")
    p_imp.add_argument("--sheet", type=str, default=None, help="Sheet name (default: first sheet)")
    p_imp.add_argument("--header-row", type=int, default=None, help="1-based Excel header row number (default: 1)")
    p_imp.add_argument("--col-id", type=str, default=None, help="ID column letter or header name")
    p_imp.add_argument("--col-question", type=str, default=None, help="Question column letter or header name")
    p_imp.add_argument("--col-expected-answer", type=str, default=None, help="Expected answer column")
    p_imp.add_argument("--col-expected-behavior", type=str, default=None, help="Expected behavior column")
    p_imp.add_argument("--col-expected-source", type=str, default=None, help="Expected source/citation column")
    p_imp.add_argument("--col-remarks", type=str, default=None, help="Remarks/notes column")
    p_imp.add_argument("--group-blank-id", action="store_true", help="Attach rows with blank ID as follow-up turns of the previous ID")
    p_imp.set_defaults(func=cmd_import)

    p_exp = sub.add_parser("export", help="Export uat_results.json to UTF-8-BOM CSV for Excel sign-off")
    p_exp.add_argument("results", type=Path, help="Path to uat_results.json")
    p_exp.add_argument("-o", "--output", type=Path, required=True, help="Output .csv path")
    p_exp.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
