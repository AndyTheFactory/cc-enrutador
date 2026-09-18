# Compatibility fixtures

This directory is reserved for **sanitized** fixtures derived from real Claude Code traffic
only when synthetic fixtures cannot reproduce an observed compatibility difference.

Do not commit broad session captures.

Before adding a fixture:

1. run `python scripts/sanitize_capture.py input.json output.json`;
2. manually inspect the output for credentials, source code, personal paths, repository names,
   account/session identifiers, and unnecessary prompt content;
3. reduce the fixture to the smallest protocol shape that reproduces the behavior;
4. add a regression test explaining why the fixture is needed.

No real-traffic fixture is currently committed because no M4 compatibility mismatch has yet
been observed in this repository environment.
