# Practical Evidence

No-spend practical gates prove a change works through the closest realistic
runtime boundary available after unit and local CI gates pass.

Evidence files live in this directory as compact JSON so PRs can cite exact
commands without relying on model memory or prose claims.

Required JSON fields:

- `gate`: stable evidence name
- `command`: exact command or harness that produced the evidence
- `status`: `pass` or `fail`; `make practical-gate` only accepts `pass`
- `timestamp`: UTC timestamp for when evidence was captured
- `summary`: concise human-readable result

Guidelines:

- Prefer Spy/Noop doubles for every outbound LLM seam.
- Exercise grouped flows when behavior crosses app, persistence, background job,
  or routing boundaries.
- Do not record secrets, tokens, or raw user data.
- Keep files small enough to paste into a PR comment if needed.
