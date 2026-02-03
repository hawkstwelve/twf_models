## Architecture Guardrails (IMPORTANT)

This repository contains **two parallel systems**:

### V1 — Static Maps (Production)
- Paths:
  - `backend/`
  - `frontend/models/`
- Status: **PRODUCTION / STABLE**
- Deployed from **tagged releases only**
- Branches:
  - `main`
  - `maintenance/v1`

⚠️ **Rules for V1**
- Do NOT refactor, rename, or restructure V1 code.
- Only small, surgical fixes are allowed.
- No dependency upgrades unless strictly required.
- No architectural changes.
- Any V1 change must be safe to deploy immediately.

---

### V2 — Dynamic Tile-Based Maps (In Development)
- Paths:
  - `backend_v2/`
  - `frontend_v2/`
  - `scripts/v2/`
- Status: **EXPERIMENTAL / NOT IN PRODUCTION**
- Branch:
  - `feature/v2-tiles`

✅ **Rules for V2**
- All new development goes here.
- No imports or references to V1 code.
- No changes to V1 paths unless explicitly approved.
- Tiles must be **precomputed** and **immutable**.
- No cartopy or matplotlib in the runtime API.

---

### Cross-System Rules
- V1 and V2 must remain **fully isolated**.
- Shared utilities require explicit approval and documentation.
- Production servers must never track a moving branch.
- Production deployments are pinned to **git tags**.

---

### AI Assistant Instructions
When generating or modifying code:
- NEVER modify V1 paths unless explicitly instructed.
- NEVER suggest refactors to V1.
- Default all new functionality to V2 paths.
- Ask for confirmation before touching shared config, CI, or deployment scripts.

---

Do not create explainer documents or other documentation unless specifically asked to.

## Herbie Integration

When working on Herbie-related code:
- Read and follow docs/AI_CONTEXT_HERBIE.md
- Use Context7 only when implementing or modifying Herbie-specific behavior
- Do not compute derived fields in fetchers
- Do not delete or overwrite GRIB cache files