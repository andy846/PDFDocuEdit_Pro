# PDFDocuEdit Pro v2.5.14

This release brings recent viewer and search fixes together with in-place AcroForm editing and a managed Windows installer.

- Fill existing AcroForm fields on the PDF page. The right panel lists fields; edits remain in a per-document draft until Apply and can be undone in one step.
- Preview staged form values, retain drafts when switching tools or tabs, and choose how to handle them on save or close. Signature appearances remain images, not digital signatures; XFA forms remain unsupported.
- Improve Windows 11 viewer corners, maximized edges, reading-area spacing, and the toolbar boundary.
- Add page numbers and Delete/Extract actions to search results, with related viewer interaction fixes.
- Restore an Inno Setup download. The new Setup installs the same managed Launcher, version directory, and update state as the Managed Portable package.

## Install or update

For a new Windows x64 installation, run `PDFDocuEdit-Pro-v2.5.14-Setup-Windows-x64.exe` or extract the Managed Portable ZIP and start `Launcher.exe`. The installer uses a new folder; it will not overwrite an existing managed deployment or legacy direct installation. Existing managed installations can use Help > Check for Updates > Download Update > Update and Restart.

The signed update ZIP and manifest are for existing managed installations. Matching SHA-256 files are included for the installer and both ZIP packages. This Setup EXE is not Authenticode-signed because no publisher certificate was configured; verify its SHA-256 checksum. The update manifest is signed with the release key.
