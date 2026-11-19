#!/usr/bin/env python3
"""
xlsx_to_uat.py - Zero-dependency Excel (.xlsx) UAT inspector, importer, in-place
format-preserving workbook updater, and CSV exporter.

Uses Python standard library only (zipfile + xml.etree.ElementTree + csv) so it works
in restricted/offline environments without openpyxl or pandas.

Subcommands:
  inspect     <file.xlsx>                         Print sheets, headers, and sample rows.
  import      <file.xlsx> -o <uat_questions.json> Convert an Excel UAT sheet to JSON.
  update-xlsx <template.xlsx> <uat_results.json> -o <out.xlsx>
                                                  Write results back into a copy of the
                                                  original .xlsx preserving all sheets,
                                                  styles, borders, merges, and formulas.
  export      <uat_results.json> -o <out.csv>     Export results to UTF-8-BOM CSV.
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


def cmd_update_xlsx(args: argparse.Namespace) -> None:
    """Write uat_results.json back into a copy of the original .xlsx, preserving all formatting."""
    if not args.template.is_file():
        raise FileNotFoundError(f"Template Excel file not found: {args.template}")
    if not args.results.is_file():
        raise FileNotFoundError(f"Results JSON not found: {args.results}")

    cfg: dict[str, Any] = {}
    if args.mapping:
        if not args.mapping.is_file():
            raise FileNotFoundError(f"Mapping file not found: {args.mapping}")
        cfg = json.loads(args.mapping.read_text(encoding="utf-8"))

    sheet = args.sheet or cfg.get("sheet")
    header_row = args.header_row if args.header_row is not None else int(cfg.get("header_row", 1))
    cols_cfg = cfg.get("columns") or {}
    out_cfg = cfg.get("output_columns") or {}
    group_blank_id = args.group_blank_id or bool(cfg.get("group_blank_id", False))

    col_id_spec = args.col_id or cols_cfg.get("id")
    col_q_spec = args.col_question or cols_cfg.get("question")
    out_ans_spec = args.col_actual_answer or out_cfg.get("actual_answer")
    out_src_spec = args.col_actual_sources or out_cfg.get("actual_sources")
    out_status_spec = args.col_status or out_cfg.get("status")
    out_comment_spec = args.col_review_comment or out_cfg.get("review_comment")

    if not any([out_ans_spec, out_src_spec, out_status_spec, out_comment_spec]):
        raise ValueError(
            "Specify at least one output column via --mapping (output_columns) or "
            "--col-actual-answer / --col-actual-sources / --col-status / --col-review-comment."
        )

    results_data = json.loads(args.results.read_text(encoding="utf-8"))
    if not isinstance(results_data, list):
        raise ValueError("Results JSON must be a list of conversation records.")

    # Index results by (case_id, 1-based turn_number)
    turn_lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for rec in results_data:
        cid = str(rec.get("id", "")).strip()
        for idx, tr in enumerate(rec.get("turns") or [], 1):
            t_num = int(tr.get("turn", idx))
            turn_lookup[(cid, t_num)] = tr

    chosen_sheet, rows = read_sheet_rows(args.template, sheet)
    hmap = _header_map(rows, header_row)

    col_id = _resolve_col(col_id_spec, hmap)
    col_q = _resolve_col(col_q_spec, hmap)
    out_ans = _resolve_col(out_ans_spec, hmap)
    out_src = _resolve_col(out_src_spec, hmap)
    out_status = _resolve_col(out_status_spec, hmap)
    out_comment = _resolve_col(out_comment_spec, hmap)

    # Map each Excel row number to its matched (case_id, turn_num)
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
            case_id = f"UAT-{auto_seq:03d}"
            last_id = case_id

        turn_counts[case_id] = turn_counts.get(case_id, 0) + 1
        key = (case_id, turn_counts[case_id])
        if key in turn_lookup:
            row_to_turn[rnum] = turn_lookup[key]

    # Patch only the target worksheet XML inside a copy of the original workbook
    ET.register_namespace("", _MAIN_NS)
    ET.register_namespace("r", _REL_NS)

    same_file = args.template.resolve() == args.output.resolve()
    write_target = args.output.with_suffix(".tmp.xlsx") if same_file else args.output
    write_target.parent.mkdir(parents=True, exist_ok=True)

    updated_rows = 0
    with zipfile.ZipFile(args.template, "r") as zin:
        _, target_xml_path = _resolve_sheet(zin, chosen_sheet)
        sheet_root = ET.fromstring(zin.read(target_xml_path))

        # Collect existing column styles from first data row as fallback for empty cells
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
            rev = tr.get("uat_review") or {}
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
        write_target.replace(args.output)

    print(
        f"Updated {updated_rows} row(s) in '{chosen_sheet}' (formatting preserved) -> {args.output}"
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
    print(f"Exported {row_count} turn row(s) -> {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-dependency Excel (.xlsx) UAT inspector, importer, updater, and CSV exporter."
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

    p_upd = sub.add_parser("update-xlsx", help="Write uat_results.json back into a copy of the original .xlsx (preserving all formatting)")
    p_upd.add_argument("template", type=Path, help="Original input .xlsx workbook")
    p_upd.add_argument("results", type=Path, help="Path to uat_results.json")
    p_upd.add_argument("-o", "--output", type=Path, required=True, help="Output .xlsx path (can be same as template to overwrite)")
    p_upd.add_argument("--mapping", type=Path, default=None, help="Path to excel_mapping.json")
    p_upd.add_argument("--sheet", type=str, default=None, help="Sheet name")
    p_upd.add_argument("--header-row", type=int, default=None, help="1-based header row number")
    p_upd.add_argument("--col-id", type=str, default=None, help="ID column letter or header name")
    p_upd.add_argument("--col-question", type=str, default=None, help="Question column (used to skip blank rows)")
    p_upd.add_argument("--col-actual-answer", type=str, default=None, help="Target column for actual answer")
    p_upd.add_argument("--col-actual-sources", type=str, default=None, help="Target column for retrieved sources")
    p_upd.add_argument("--col-status", type=str, default=None, help="Target column for PASS/PARTIAL/FAIL status")
    p_upd.add_argument("--col-review-comment", type=str, default=None, help="Target column for LLM judge review comment")
    p_upd.add_argument("--group-blank-id", action="store_true", help="Match blank-ID follow-up rows to the previous ID")
    p_upd.set_defaults(func=cmd_update_xlsx)

    p_exp = sub.add_parser("export", help="Export uat_results.json to UTF-8-BOM CSV")
    p_exp.add_argument("results", type=Path, help="Path to uat_results.json")
    p_exp.add_argument("-o", "--output", type=Path, required=True, help="Output .csv path")
    p_exp.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
