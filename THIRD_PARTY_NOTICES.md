# Third-party notices

## Ghostscript 10.05.1

The Windows distribution bundles Ghostscript for PDF/PostScript conversion.
Ghostscript is distributed under GNU Affero General Public License version 3
(with commercial licensing available separately from Artifex).
The original licence text accompanies the runtime at `ghostscript/doc/COPYING`.
Upstream source and release: https://github.com/ArtifexSoftware/ghostpdl/tree/gs10051
No Ghostscript licence text or notices have been modified.

## Lucide Icons

The user-interface icon paths are derived from the Lucide icon project.

Copyright (c) 2022 Lucide Contributors

Licensed under the ISC License: permission to use, copy, modify, and/or
distribute this software for any purpose with or without fee is hereby granted,
provided that the above copyright notice and this permission notice appear in
all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.

## Tesseract OCR 5.5.3

Windows x64 packages include Tesseract OCR 5.5.3 and the English and
Traditional Chinese trained-data files. Tesseract and the official tessdata
repositories are licensed under the Apache License 2.0.

Copyright (c) 2006-2025 Google, Inc. and other contributors.

A copy of the Apache License 2.0 must accompany the binary distribution.
Source and release information: https://github.com/tesseract-ocr/tesseract

## Leptonica

The bundled Tesseract runtime includes Leptonica. Leptonica is distributed
under a BSD 2-Clause license.

Copyright (c) 2001-2025 Leptonica contributors.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the copyright notice, conditions,
and disclaimer are retained. The software is provided "AS IS", without
warranty.

## veraPDF Greenfield 1.30.2

Windows and macOS packages include the veraPDF Greenfield validation CLI for
offline PDF/A and PDF/UA machine-verifiable conformance checks. veraPDF is
available under a dual licence: Mozilla Public License 2.0 or GNU General
Public License 3.0 or later.

Project and source information: https://github.com/veraPDF/veraPDF-apps

The selected licence text and all notices shipped by the veraPDF distribution
must accompany binary releases.

## Eclipse Temurin JRE 21

The bundled veraPDF component includes a platform-specific Eclipse Temurin
Java runtime. Eclipse Temurin OpenJDK binaries are licensed under GNU General
Public License 2.0 with the Classpath Exception.

Copyright (c) 2026 Eclipse Adoptium and OpenJDK contributors.

Release and source information: https://adoptium.net/temurin/releases/

The applicable GPLv2 and Classpath Exception texts, notices, and source offer
requirements must accompany binary releases.

## Cryptography (PyCA)

The portable updater uses cryptography 46.0.7 for Ed25519 signature verification.
It is distributed under the Apache License 2.0 or BSD 3-Clause license.
The bundled cryptography distribution metadata includes its license texts and
notices for its OpenSSL and Rust dependencies. Source: https://github.com/pyca/cryptography


## Document Designer components (V3 production builds)

qpdf 12.4.2 is distributed under Apache License 2.0. Its LICENSE.txt and
NOTICE.md accompany the pinned Windows runtime. Source: https://github.com/qpdf/qpdf

Noto Sans and Noto Sans CJK HK fonts are distributed under the SIL Open Font
License 1.1. Their OFL texts accompany the font files.
Sources: https://github.com/notofonts/noto-fonts and https://github.com/notofonts/noto-cjk

Segno 1.6.6 is distributed under BSD 3-Clause.
Source: https://github.com/heuer/segno

python-barcode 0.16.1 is distributed under MIT.
Source: https://github.com/WhyNotHugo/python-barcode

The installed package licence files and the composition asset manifest
identify the exact versions and checksums used by the build.

## Optional private Windows account test build

Supabase Python SDK 2.32.0 and keyring 25.7.0 are MIT licensed.
Sources: https://github.com/supabase/supabase-py and https://github.com/jaraco/keyring

HTTPX 0.28.1 is BSD 3-Clause licensed; certifi 2026.7.22 uses MPL 2.0
for its public CA certificate bundle. These optional components are pinned
in requirements-auth-windows.lock; installed distribution metadata and
licence texts accompany the private auth build. Public builds do not require
the Supabase/keyring account feature.
