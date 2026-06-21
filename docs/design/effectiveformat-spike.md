# Design: effectiveFormat spike — cell formatting assertions via API

**Date:** 2026-06-20  
**Issue:** [#54](https://github.com/khuisman/mcp-gee-sweet/issues/54)  
**Status:** complete

> Point-in-time spike. Confirms that formatting applied via `batch_update` is fully readable back through `get_sheet_data(include_grid_data=True)`, without a browser.

---

## What we tested

Applied three separate formats to fixture cells using `batch_update → repeatCell`:
1. **Bold** on A1 (text cell)
2. **Italic + background color** on B1 (text cell)
3. **Currency number format** on B2 (numeric cell)

Then read back via `get_sheet_data(spreadsheet_id, sheet="Sales", range="A1:B2", include_grid_data=True)`.

---

## Response shape

Each cell object under `sheets[0].data[0].rowData[row].values[col]` has:

```
{
  userEnteredValue:  { stringValue | numberValue | boolValue | formulaValue }
  effectiveValue:    { stringValue | numberValue | ... }   # post-formula
  formattedValue:    "..."                                  # display string
  userEnteredFormat: { ... }                               # what was explicitly set
  effectiveFormat: {
    backgroundColor:      { red, green, blue }
    backgroundColorStyle: { rgbColor: { red, green, blue } }
    padding:              { top, right, bottom, left }
    horizontalAlignment:  "LEFT" | "CENTER" | "RIGHT"
    verticalAlignment:    "TOP" | "MIDDLE" | "BOTTOM"
    wrapStrategy:         "OVERFLOW_CELL" | "WRAP" | "CLIP"
    hyperlinkDisplayType: "PLAIN_TEXT" | "LINKED"
    numberFormat:         { type, pattern }               # only if set
    textFormat: {
      fontFamily:      "Arial"
      fontSize:        10
      bold:            false
      italic:          false
      strikethrough:   false
      underline:       false
      foregroundColor: { red, green, blue }               # {} means default (black)
      foregroundColorStyle: { rgbColor: { ... } }
    }
  }
}
```

## What is assertable

| Field | Confirmed | Notes |
|---|---|---|
| `effectiveFormat.textFormat.bold` | ✅ | `true`/`false` |
| `effectiveFormat.textFormat.italic` | ✅ | `true`/`false` |
| `effectiveFormat.textFormat.underline` | ✅ | in schema; not separately tested |
| `effectiveFormat.textFormat.strikethrough` | ✅ | in schema; not separately tested |
| `effectiveFormat.textFormat.fontSize` | ✅ | integer |
| `effectiveFormat.textFormat.fontFamily` | ✅ | string |
| `effectiveFormat.textFormat.foregroundColor` | ✅ | RGB — see float note below |
| `effectiveFormat.backgroundColor` | ✅ | RGB — see float note below |
| `effectiveFormat.horizontalAlignment` | ✅ | `LEFT` for text, `RIGHT` for numbers by default |
| `effectiveFormat.verticalAlignment` | ✅ | string |
| `effectiveFormat.wrapStrategy` | ✅ | string |
| `effectiveFormat.numberFormat.type` | ✅ | `CURRENCY`, `PERCENT`, `DATE`, etc. |
| `effectiveFormat.numberFormat.pattern` | ✅ | format string |
| `formattedValue` | ✅ | rendered display string — simplest way to assert number format |

## RGB float precision

The API returns RGB as floats in [0, 1]. `0.9` is transmitted as `0.8980392` (229/255 rounded). When asserting colors, use approximate matching (± 1/255 ≈ 0.004), or compare `round(v * 255)` as integers.

Example: `{red:1, green:0.9, blue:0.6}` comes back as `{red:1, green:0.8980392, blue:0.6}`.

## Fixture strategy

The fixture spreadsheet has no pre-applied formatting (all cells use spreadsheet defaults). Formatting tests follow a setup→assert→teardown pattern:

1. **Setup**: `batch_update` with `repeatCell` to apply the format to target cells.
2. **Assert**: `get_sheet_data(include_grid_data=True, range=<target>)` and inspect `effectiveFormat`.
3. **Teardown**: `batch_update` with `repeatCell { cell: {}, fields: "userEnteredFormat" }` to clear all custom formatting from those cells.

This keeps the fixture clean between tests and avoids needing a dedicated "Formatting" sheet.
