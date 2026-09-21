# PDFDocuEdit Pro v2.5.12

Bug fix release for low-resolution displays, Merge PDF responsiveness and Windows taskbar pinning.

- Adapt 40 dialogs to the available screen area, with scrollable content and reachable primary actions. Batch Print and text extraction stack controls on narrow screens.
- Fix Inspector, search, thumbnail sidebar and Analysis Results layouts on small windows. Temporary toolbox collapse preserves the saved preference.
- Add Merge PDF files immediately and read their details in the background. Use a lightweight table model and safely ignore obsolete results.
- Reduce default merge save overhead; optional compact output remains available.
- Share the Windows taskbar application identity and set pinned-window relaunch to the stable Launcher.exe path.
- Retain virtualized large-document Organizer, drag reorder and rounded thumbnails from v2.5.11.

## Update

Existing Managed Portable installations: Help > Check for Updates > Download Update > Update and Restart.

For a new deployment, extract the entire Managed Portable ZIP into a new writable folder and run Launcher.exe. Do not extract it over an existing deployment.

For the taskbar fix, remove old pins, start Launcher.exe, then pin the running PDFDocuEdit Pro window. Existing pins are not rewritten automatically. Explorer grouping depends on recreating the pin; automated tests validate the native window properties.

Update manifests are Ed25519-signed; ZIP checksums are included. This is not a claim of Windows Authenticode publisher signing.
