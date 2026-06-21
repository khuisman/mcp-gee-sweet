# QA Run — sheets delete/clear tools
**Date:** 2026-06-21
**Branch:** feat/sheets-delete-clear
**Auth:** service_account
**Fixture:** TEST_SPREADSHEET_ID (Sales / Empty / Notes & Misc)

---

## TC-S25: Delete an existing sheet tab ✅
Setup: created TempTab via `create_sheet`, then deleted it.
- TempTab absent from `list_sheets` after deletion ✓
- No `error` field in response ✓

## TC-S26: Delete a non-existent sheet returns error ✅
- Response: `{"error":"Sheet 'DoesNotExist' not found"}` ✓
- No API batchUpdate made ✓

## TC-S27: Delete a single row ✅
Deleted row index 4 (Gizmo) from Sales.
- Row 4 content (Gizmo) gone after deletion ✓
- Former row 5 (Totals) shifted up correctly ✓
- Totals recalculated: 650→350, 670→360, 705→415 ✓

## TC-S28: Delete a range of rows ✅
Deleted rows 2–4 (0-based, inclusive) = Gadget/Donut/Gizmo.
- Three rows removed; Widget and Totals remain ✓
- Totals recalculated to Widget-only values (100/120/140) ✓

## TC-S29: Delete rows — sheet not found returns error ✅
- Response: `{"error":"Sheet 'NoSuchSheet' not found"}` ✓

## TC-S30: Delete a single column ✅
Deleted column index 1 (Q1/column B) from Sales.
- Q1 column removed; Q2 and Q3 shifted left to become B and C ✓
- Totals recalculated correctly (670/705) ✓

## TC-S31: Delete a range of columns ✅
Deleted column indices 2–3 (inclusive) = Q2 and Q3.
- Two columns removed; only Product and Q1 remain ✓
- Inclusive end index handled correctly (end_column=3 → endIndex=4) ✓

## TC-S32: Delete columns — sheet not found returns error ✅
- Response: `{"error":"Sheet 'NoSuchSheet' not found"}` ✓

---

## TC-W29: Clear a specific range ✅
Cleared Sales!A1:C5.
- Cells A1:C5 empty after clear ✓
- Column D (Q3) untouched ✓
- Row 6 (Totals) untouched; SUM formulas recalculated correctly ✓
- No `error` field ✓

## TC-W30: Clear entire sheet ✅
Cleared all values from Notes & Misc (no range argument).
- `values: []` returned by get_sheet_data ✓
- No `error` field ✓

## TC-W31: Clear values — sheet name with spaces ✅
Cleared `Notes & Misc`!B2:D4.
- `clearedRange` in response: `'Notes & Misc'!B2:D4` — sheet name correctly single-quoted ✓
- No `error` field ✓

## TC-W32: Clear non-existent range — API behaviour ✅
Cleared Sales!Z100:Z200 (out of populated bounds).
- API accepted range without error ✓
- `clearedRange: "Sales!Z100:Z200"` returned ✓

---

## Summary
12/12 tests passed. All new tools exercised live against fixture. Fixtures restored to known state after each destructive test.
