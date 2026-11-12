# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Send a description of the problem, the steps to reproduce it and the affected version to
**info@nextmind.it**. We aim to acknowledge reports within 5 working days.

## Scope and design assumptions

JanusTower is a **local, single-user** tool that reads Google Cloud data with the signed-in user's OAuth token:

- it listens on `127.0.0.1` by default and is not meant to be exposed on a network or shared between users;
- OAuth tokens and scan results (which can include personal data) are stored in plain text in the local `data/` folder;
- all calls to Google Cloud are read-only.

Reports about these documented assumptions are welcome as improvement suggestions; reports that break them
(for example code execution from scanned data, access to another user's session, or any write to Google Cloud)
are treated as vulnerabilities.
