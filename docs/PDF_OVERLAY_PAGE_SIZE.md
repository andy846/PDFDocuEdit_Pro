# PDF Workspace — Overlay PDFs page size

Development fix; not included in the published v3.0.5 binaries.
This guide covers the editor's **Overlay PDFs** tool, separate from Document Designer's PDF Overlay projects.

## Two independent controls

- **Output page size → Keep target page size**: default, keeps each target page's existing paper dimensions and orientation.
- **Output page size → Match paired template page size**: uses the displayed paper dimensions of the template page paired with that target page.
- **Template content → Fit template to output page**: scales template artwork proportionally to fit the chosen output canvas.
- **Template content → Template at 100% (original content size)**: retains template artwork's original physical size.

For an A4 template and a Letter target, matching the template produces **210 × 297 mm**. Keeping the target produces **215.9 × 279.4 mm**. Both template scaling choices respect the independently selected output paper size.

Target content stays at **100%**, anchored at its original displayed position. Changing paper does not silently scale target text. Smaller paper can clip edges; inspect the before/after preview. The preview displays actual output dimensions and uses the same PDF operation as export.

## Pairing and preservation

Repeat-last and cycle follow each paired template page, including templates with mixed sizes. Matching-pages-only leaves unpaired target pages unchanged.

The operation preserves searchable content, existing visible annotations/forms, links, metadata and bookmarks, with normal background processing and validated atomic output. Original page content remains clipped to its original visible area when the paper grows. If resizing would expose an annotation/form previously outside that area, the tool blocks that file and identifies the source page; keep target size or flatten the visible target appearances first.

The default remains the existing target-paper behaviour. No project-format, public-version or dependency changes are required.
