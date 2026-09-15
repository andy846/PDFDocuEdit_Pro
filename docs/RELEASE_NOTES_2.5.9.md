# PDFDocuEdit Pro v2.5.9

## Bug fixes

- Remove the extra native line above document tabs.
- Create thumbnail widgets only near the viewport, reducing initialization work for documents with many pages.
- Prioritize visible thumbnails during fast scrolling, show page-number loading placeholders, restore cached images, and stop repeated failed renders.
- Refresh Continuous and Facing layouts during ongoing scrolling instead of waiting for scrolling to stop.
- Refill page renders skipped by the prefetch limit and prioritize visible pages.
- Start Facing with pages 1 + 2, then 3 + 4; an odd final page is displayed alone.

## Windows packages

- Managed Portable ZIP: extract the entire package into an approved writable location and start Launcher.exe.
- Update ZIP, update.json and update.sig: signed artifacts for the existing managed updater.
- Do not extract the Managed Portable ZIP over an existing managed installation.

Repository visibility is unchanged. Anonymous update checks cannot access private GitHub Releases; if the repository is private, download access requires an authorized GitHub account.

## Validation

- 558 automated tests passed; Ruff and source verification passed.
- Frozen Windows navigation acceptance passed: page centering, Facing pairs, thumbnail navigation and status page synchronization.
