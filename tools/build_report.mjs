import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('Usage: build_report.mjs <input.json> <output.xlsx>');
const rows = JSON.parse(await fs.readFile(inputPath, 'utf8'));
const headers = ['Match Score','Recommendation','Eligibility Status','Seniority','Location Verified','Experience Verified','Posting Date Verified','Original Page Verified','Confidence','Job Title','Company','Company Type','Location','Work Mode','Salary','Experience Required','Posting Date','Freshness','Primary Skills','Matching Skills','Skill Gaps','Cloud/DevOps Match','Why It Matches','Potential Concerns','Source','Original Company URL','Application URL','Job ID','Date Discovered','Status'];
const fields = ['match_score','recommendation','eligibility_status','seniority','location_verified','experience_verified','posting_date_verified','original_url_verified','confidence','title','company','company_type','location','work_mode','salary','experience','posting_date','freshness','primary_skills','matching_skills','skill_gaps','cloud_devops_match','why_it_matches','potential_concerns','source','original_url','application_url','external_job_id','first_seen','status'];
const wb = Workbook.create();
const sheetSpecs = [
  ['Top Matches', r => r.match_score >= 70 && r.recommendation !== 'DO NOT INCLUDE'],
  ['All New Jobs', r => ['NEW','UPDATED'].includes(r.status) && r.recommendation !== 'DO NOT INCLUDE'],
  ['Cloud & DevOps', r => r.cloud_devops_match === 'High' && r.recommendation !== 'DO NOT INCLUDE'],
  ['High Salary', r => r.salary !== 'Not disclosed' && /(?:10|1[2-9]|[2-9]0)\s*(?:lpa|lakh)/i.test(r.salary)],
  ['Previously Seen', r => r.status === 'SEEN'],
  ['Rejected Summary', r => r.recommendation === 'DO NOT INCLUDE'],
];
for (const [name, predicate] of sheetSpecs) {
  const sheet = wb.worksheets.add(name); sheet.showGridLines = false;
  const subset = rows.filter(predicate).sort((a,b) => (b.match_score || 0) - (a.match_score || 0));
  sheet.getRange('A1:AD1').merge();
  sheet.getRange('A1').values = [[`${name} — Aryan Kumar Job Finder`]];
  sheet.getRange('A1:AD1').format = { fill: '#0F2A43', font: { bold: true, color: '#FFFFFF', size: 14 }, horizontalAlignment: 'left' };
  sheet.getRange('A3:AD3').values = [headers];
  sheet.getRange('A3:AD3').format = { fill: '#146C94', font: { bold: true, color: '#FFFFFF' }, wrapText: true, horizontalAlignment: 'center' };
  const values = subset.map(row => fields.map(field => row[field] ?? ''));
  if (values.length) {
    sheet.getRangeByIndexes(3, 0, values.length, headers.length).values = values;
    sheet.getRange(`A4:AD${values.length + 3}`).format.wrapText = true;
    sheet.getRange(`A4:A${values.length + 3}`).format.numberFormat = '0';
    sheet.getRange(`J4:J${values.length + 3}`).format.numberFormat = 'yyyy-mm-dd';
    sheet.getRange(`A4:A${values.length + 3}`).conditionalFormats.add('cellIs', { operator: 'greaterThanOrEqual', formula: 85, format: { fill: '#BBF7D0', font: { bold: true, color: '#166534' } } });
    sheet.getRange(`A4:A${values.length + 3}`).conditionalFormats.add('cellIs', { operator: 'between', formula: [70, 84], format: { fill: '#DBEAFE', font: { color: '#1D4ED8' } } });
    sheet.tables.add(`A3:AD${values.length + 3}`, true, `${name.replace(/[^A-Za-z]/g, '')}Table`);
  }
  sheet.freezePanes.freezeRows(3);
  sheet.getRange('A:AD').format.columnWidth = 15;
  for (const col of ['J','K','S','T','U','W','X','Y','Z','AA','AB']) sheet.getRange(`${col}:${col}`).format.columnWidth = 28;
  sheet.getRange('A1:AD3').format.rowHeight = 24;
}
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputPath);
const preview = await wb.render({ sheetName: 'Top Matches', range: 'A1:W10', scale: 1, format: 'png' });
await fs.writeFile(outputPath.replace(/\.xlsx$/, '.preview.png'), new Uint8Array(await preview.arrayBuffer()));
