from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import List

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.formatting.rule import CellIsRule


def _add_sheet(wb: Workbook, name: str, headers: List[str], rows_values: List[List[object]]):
    sheet = wb.create_sheet(title=name)
    # Title row (A1:AD1)
    sheet.merge_cells('A1:AD1')
    title_cell = sheet['A1']
    title_cell.value = f"{name} — Aryan Kumar Job Finder"
    title_cell.fill = PatternFill(start_color='0F2A43', end_color='0F2A43', fill_type='solid')
    title_cell.font = Font(bold=True, color='FFFFFF', size=14)
    title_cell.alignment = Alignment(horizontal='left')

    # Header row at A3:AD3
    for col_idx, header in enumerate(headers, start=1):
        cell = sheet.cell(row=3, column=col_idx, value=header)
        cell.fill = PatternFill(start_color='146C94', end_color='146C94', fill_type='solid')
        cell.font = Font(bold=True, color='FFFFFF')
        cell.alignment = Alignment(horizontal='center', wrap_text=True)

    # Data starting at row 4
    start_row = 4
    for r_idx, row in enumerate(rows_values, start=start_row):
        for c_idx, value in enumerate(row, start=1):
            cell = sheet.cell(row=r_idx, column=c_idx, value=value)
            # Original Company URL is column Z (26), Application URL is AA (27)
            if c_idx == 26 and value:
                cell.hyperlink = value
                cell.style = 'Hyperlink'
            if c_idx == 27 and value:
                cell.hyperlink = value
                cell.style = 'Hyperlink'

    # Table and filters
    end_row = start_row + max(0, len(rows_values) - 1)
    if end_row >= start_row:
        ref = f"A3:AD{end_row}"
        table_name = f"{name.replace(' ', '')}Table"
        table = Table(displayName=table_name, ref=ref)
        style = TableStyleInfo(name='TableStyleMedium9', showFirstColumn=False,
                               showLastColumn=False, showRowStripes=True, showColumnStripes=False)
        table.tableStyleInfo = style
        sheet.add_table(table)

    # Freeze header rows (freeze rows 3 -> freeze at A4)
    sheet.freeze_panes = 'A4'

    # Default column widths
    for col in range(1, 30):  # A..AD (30 columns)
        sheet.column_dimensions[sheet.cell(row=3, column=col).column_letter].width = 15

    # Wider columns for certain letters
    wide_cols = ['J', 'K', 'S', 'T', 'U', 'W', 'X', 'Y', 'Z', 'AA', 'AB']
    for col in wide_cols:
        sheet.column_dimensions[col].width = 28

    # Conditional formatting on match score column (A)
    score_col = 'A'
    if end_row >= start_row:
        sheet.conditional_formatting.add(f"{score_col}{start_row}:{score_col}{end_row}",
                                         CellIsRule(operator='greaterThanOrEqual', formula=['85'], stopIfTrue=True,
                                                    fill=PatternFill(start_color='BBF7D0', end_color='BBF7D0', fill_type='solid'),
                                                    font=Font(bold=True, color='166534')))
        sheet.conditional_formatting.add(f"{score_col}{start_row}:{score_col}{end_row}",
                                         CellIsRule(operator='between', formula=['70', '84'], stopIfTrue=True,
                                                    fill=PatternFill(start_color='DBEAFE', end_color='DBEAFE', fill_type='solid'),
                                                    font=Font(color='1D4ED8')))


def generate_report(rows: list[dict], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / f'Aryan_Job_Report_{date.today().isoformat()}.xlsx'

    headers = ['Match Score','Recommendation','Eligibility Status','Seniority','Location Verified','Experience Verified','Posting Date Verified','Original Page Verified','Confidence','Job Title','Company','Company Type','Location','Work Mode','Salary','Experience Required','Posting Date','Freshness','Primary Skills','Matching Skills','Skill Gaps','Cloud/DevOps Match','Why It Matches','Potential Concerns','Source','Original Company URL','Application URL','Job ID','Date Discovered','Status']
    fields = ['match_score','recommendation','eligibility_status','seniority','location_verified','experience_verified','posting_date_verified','original_url_verified','confidence','title','company','company_type','location','work_mode','salary','experience','posting_date','freshness','primary_skills','matching_skills','skill_gaps','cloud_devops_match','why_it_matches','potential_concerns','source','original_url','application_url','external_job_id','first_seen','status']

    # Sheet specifications: name and predicate function
    def pred_top(r): return (r.get('match_score') or 0) >= 70 and r.get('recommendation') != 'DO NOT INCLUDE'
    def pred_all_new(r): return r.get('status') in {'NEW','UPDATED'} and r.get('recommendation') != 'DO NOT INCLUDE'
    def pred_cloud(r): return r.get('cloud_devops_match') == 'High' and r.get('recommendation') != 'DO NOT INCLUDE'
    def pred_high_salary(r):
        s = r.get('salary') or ''
        import re
        return bool(re.search(r"(?:10|1[2-9]|[2-9]0)\s*(?:lpa|lakh)", s, flags=re.I)) and r.get('recommendation') != 'DO NOT INCLUDE'
    def pred_seen(r): return r.get('status') == 'SEEN'
    def pred_rejected(r): return r.get('recommendation') == 'DO NOT INCLUDE'

    sheet_specs = [
        ('Top Matches', pred_top),
        ('All New Jobs', pred_all_new),
        ('Cloud & DevOps', pred_cloud),
        ('High Salary', pred_high_salary),
        ('Previously Seen', pred_seen),
        ('Rejected Summary', pred_rejected),
    ]

    wb = Workbook()
    # remove default sheet
    default = wb.active
    wb.remove(default)

    for name, predicate in sheet_specs:
        subset = [r for r in rows if predicate(r)]
        subset_sorted = sorted(subset, key=lambda x: (-(x.get('match_score') or 0)))
        values = []
        for r in subset_sorted:
            row_vals = []
            for field in fields:
                v = r.get(field, '')
                # Keep application and original url as hyperlinks by storing raw URL here; tests will convert to hyperlink
                row_vals.append(v)
            values.append(row_vals)
        _add_sheet(wb, name, headers, values)

    wb.save(output)
    return output
