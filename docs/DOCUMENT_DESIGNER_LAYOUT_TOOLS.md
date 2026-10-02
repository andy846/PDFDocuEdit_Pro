# Document Designer: precise layout tools

Implementation checkpoint: 2026-10-03. Applies to template projects and PDF envelope overlay projects in the development worktree.

## User operation

### Numeric size and rotation

Select one object and use Properties > Geometry to enter X/Y/W/H in millimetres and Angle in degrees. Width and height describe the unrotated object box. Positive angles turn clockwise around the box centre.

For multiple objects, use Ctrl-click or drag a selection rectangle, then open Properties > Geometry. Set W, H and/or Angle, check only the values to apply, and click **Apply to selected**. Editing a value checks that setting automatically. Unchecked dimensions, individual positions, text, fonts, barcode profiles and rules are retained. A batch change is one Undo action. Different widths/heights are initially represented by the first selected object; unchecked values are never unified implicitly.

An invalid batch is rejected before changing any selected object. A rotation may translate the object minimally to keep its rotated edges on the page. An object larger than the page must first be resized.

The Layout menu also offers clockwise/counterclockwise 90-degree rotation and reset. Template canvas right-click > Arrange includes these rotation commands. Rotation supports text, images, lines, rectangles, Code 128, I25 and QR objects. The common PDF renderer rotates vector content and embedded text; text remains searchable. The existing PDF background is unaffected.

### Rulers, snapping and measurement

Open **Layout** on the project toolbar, or the project View menu.

- Millimetre rulers: enabled initially; follow page size, pan and zoom.
- Snap to page and object edges / centres: enabled initially. Moving a selection snaps its enclosing bounds to page edges/centres or other object edges/centres. Pink guides show the matching axis. Multiple selected objects retain their spacing.
- Grid and 5 mm grid snapping: optional, using the existing template controls and the same controls added to overlay projects. Edge/centre snapping takes priority.
- Hold **Alt** during dragging to temporarily bypass both snapping modes.
- Measure distance: enable, then drag between two canvas points. The status area reports distance, horizontal difference and vertical difference in millimetres. Disable the tool to resume normal selection/movement. Measurements are visual aids and are not saved as document objects or printed.

Arrow movement retains the existing 0.5 mm step, or 5 mm with Shift. Rotated bounds are used when keeping moved/resized selections inside the page.

## Architecture and compatibility

- Rotation geometry lives in `composition/template/geometry.py`; models and PDF renderers do not depend on Qt.
- Both designer workspaces share the canvas, rulers and layout command adapter.
- Template schema is now **7**; schemas 1–6 still load, with missing rotation set to zero. PDF envelope projects use schema **2**, migrating schema 1 with zero rotation.
- New files saved by this build require a compatible reader. Earlier application builds reject newer schemas; do not downgrade a rotated project by manually changing its version number.
- Explicit nonzero rotation in a legacy schema is rejected, avoiding silently unrotated output.
- Overlay barcode verification crops the rotated bounding rectangle and reports the configured angle. The earlier optional-barcode behaviour is retained.
- No new dependency, public version change, whole-viewer rewrite or production packaging is part of this checkpoint.

## Targeted verification

Only tests related to the changes were run; full regression and Windows packaging remain deferred at the user's request.

- 42 focused cases: vector rotation at 0/37/90/180/270 degrees, searchable text, image orientation, subsequent unrotated content, Code 128/I25/QR decoding and preview/output agreement, numeric batch editing/Undo, atomic rejection, snapping/group spacing/Alt bypass, measurement, existing drag/resize and multi-font behaviour, template/overlay migrations, sequence/Excel schema compatibility and optional barcodes.
- 5 focused UI cases at 200% scaling: rulers/measurement/narrow Properties without horizontal scrolling, overlay batch geometry and selection-dependent rotation actions, main-window controls in light/dark themes at 960 x 640, and Layout button icons following theme changes in both workspaces.
- Windows Segoe UI was explicitly loaded for offscreen visual inspection; both theme captures showed zero horizontal scrolling in Properties.
- The new QApplication fixture is held for the test session, avoiding native Qt lifetime failures when these tests are combined with main-window tests.

Save current projects and reopen the application to load the new designer UI. Mode switching itself continues to retain project state.
