# Low-resolution UI audit

## Coverage and target sizes

Forty custom dialog interfaces are exercised individually at five available desktop sizes, in Qt logical pixels: 1280×680, 1024×700, 800×560, 853×440 and 640×440. Logical pixels account for Windows display scaling; a physical display can offer substantially less usable space at 125% or 150%. Work-area bounds exclude the taskbar, and the implementation reserves space for window decorations.

The audit uses the application's production light theme. Six representative previews were visually reviewed at 853×440: main window, Preferences, Batch Print, Organizer, compression and region text extraction. These are simulated work-area tests, not a claim that every physical monitor/DPI combination was manually exercised.

## Interfaces checked individually

| Interface | Treatment |
| --- | --- |
| Watermark | Scrollable form, fixed actions |
| Barcode scan | Scrollable form, fixed actions |
| Barcode results | Scrollable content, table viewport |
| Batch Print | Columns stack below 980 logical pixels; fixed Start/Cancel/Close |
| Compress PDFs | Scrollable options, fixed Start/Cancel |
| Merge PDFs | Virtual file table within screen-bounded dialog |
| Overlay PDFs | Scrollable form, fixed actions |
| Compare PDFs | Screen-bounded scrollable workspace |
| Office conversion | Scrollable options and tables |
| PostScript conversion | Scrollable options and tables |
| Text conversion | Scrollable options and tables |
| Page count report | Scrollable options and results |
| Spreadsheet merge | Scrollable options and tables |
| Advanced Page Organizer | Scrollable body, independent plan actions; nested tool scrolling |
| Document information | Scrollable properties |
| Print options | Scrollable options, fixed actions |
| PDF form editor | Scrollable workspace, fixed actions |
| OCR options | Scrollable form, fixed actions |
| OCR text results | Scrollable text and actions |
| Insert blank pages | Scrollable settings, fixed actions |
| Crop page plan | Scrollable preview and controls |
| Interleave pages | Scrollable settings and preview |
| Organizer background job | Fixed Cancel action |
| Split page plan | Scrollable settings and preview |
| Page selection | Scrollable form, fixed actions |
| Insert pages | Scrollable form, fixed actions |
| Split PDF | Scrollable form, fixed actions |
| Readme/help | Scrollable reference |
| Find and open PDF | Scrollable options and results |
| Encrypt PDF | Scrollable form, fixed actions |
| Decrypt PDF | Scrollable form, fixed actions |
| Keyboard shortcuts | Scrollable filter/table, fixed Close |
| Signature appearance | Scrollable drawing surface, fixed actions |
| Region text extraction | Controls and preview stack below 900 logical pixels |
| Undo history | Scrollable history, fixed actions |
| Command palette | Screen-bounded popup |
| Deep search | Scrollable options/results, independent actions |
| Diagnostics | Scrollable details, fixed actions |
| Preferences | Scrollable settings and shortcuts, fixed OK/Cancel |
| Update dialog | Scrollable notes, fixed update/close actions |

Main-window checks additionally cover visible toolbar controls at four small screen sizes. Nonessential toolbar duplicates collapse into existing menu/shortcut access, while page navigation, zoom entry and layout selection remain reachable. Welcome, context options and all four Analysis tabs have scrollable content. Opening a document panel on a narrow window temporarily collapses the toolbox without changing its saved preference; panel sizes use actual available width rather than an assumed 900 pixels. Native operating-system file/password/message dialogs remain under Qt/Windows management.

## Shared behavior

`ui/responsive.py` preserves each dialog's original layout inside a resizeable scroll area. Standard footer actions sit outside the body viewport. Horizontal scrolling remains available when content genuinely needs more width, such as a signature canvas or wide comparison controls. Fonts are not reduced to make content fit.

Dialog geometry uses the current screen, clamps restored off-screen positions, and responds to monitor/work-area changes. Nested scroll areas reveal keyboard-focused controls from inside out. Inline validation messages are brought into view. Reopening a dialog reuses its scroll shell rather than nesting another shell.

Regression tests also retain Organizer dragging/cancellation and the earlier Merge and Windows taskbar fixes. Run `python -m pytest tests/test_low_resolution.py` for the screen-size matrix.

## Verification (2026-09-21)

The 40-dialog matrix covers five available-screen sizes, including 640 x 440 logical pixels. Six rendered previews were reviewed with the production light theme: main window, Batch Print, Preferences, Organizer, compression and region text extraction. Analysis Results uses two columns of action buttons and separates grouping from export-row selection so controls fit narrow panels.

The initial complete suite finished with 804 passed and two layout failures. Both were fixed: narrow-window Inspector allocation and Analysis Results action overflow. After those fixes, the affected UI/Organizer suite passed 245 tests and the Analysis/low-resolution suite passed 237 tests (these runs overlap). The complete suite was not rerun after the fixes. Ruff, source verification and `git diff --check` passed. Earlier combined checks also covered Merge and Windows taskbar changes.

These are automated logical-screen geometry checks and rendered preview reviews, not a claim that every physical monitor or Windows scaling configuration has been manually tested. No new GitHub release was published as part of this change.
