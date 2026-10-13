# Windows qpdf reputation detection review

Observed user report: the original packaged qpdf.exe was quarantined by Symantec Endpoint Protection as WS.Reputation.1 (Insight Network Threat). This records a suspected false positive; it is not an antivirus vendor clearance or an instruction to disable protection.

## Expected packaged dependency

- Component: official qpdf 12.4.2, Windows MSVC x64.
- Source: https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-msvc64.zip
- Expected qpdf.exe SHA256: `1bdaf878f37eaffea1ea3c30591214c77636a0f2fc7432427516b6e22e36c0ff`.
- The official bundled executable has no Windows Authenticode signature (local read-only signature check: NotSigned). This may influence reputation; it does not establish whether the reported detection is a false positive.
- Local bundled copy matches the pinned manifest; Windows executable bytes are unchanged by issue #14.
- Purpose: independent PDF syntax/stream checks and PDF rewriting/assembly. Quarantine may block Font Preflight repair, PDF normalisation and production assembly. Publication checks must remain mandatory.

## Operator / IT handling

Ask the antivirus administrator to compare the detection's actual path and hash with this dependency, retain detection metadata and submit the suspected false positive to Broadcom. A filename alone does not establish identity. Do not disable antivirus, bypass application verification or exclude the entire installation folder. Restore/allow a verified dependency only under the organisation's approved security policy. No files or support messages have been submitted by Codex.

Broadcom explains that legitimate files may receive WS.Reputation.1 reputation detections: https://knowledge.broadcom.com/external/article/191764/endpoint-protection-detects-known-good-a.html
Submission guidance: https://knowledge.broadcom.com/external/article/178170/submit-false-positives-detected-by-endpo.html
