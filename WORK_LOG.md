# Work Log - Backend Interface Sync

> Historical archive: this log records an earlier interface contract. References to free-text AI requirements, account flows, Studio, or AI Lab are not current product promises. Use `PRODUCT.md`, `docs/项目业务审核与修改报告.md`, and the running local UI as the current source of truth.

Date: 2026-05-25

## Completed

- Rebuilt the backend API contract around the redesigned frontend board studio.
- Added `python-multipart` to `backend/requirements.txt`; dependency installation is left to the user.
- Added board-aware Pydantic models for board specs, board assets, AI experiment requests, task envelopes, and review responses.
- Reworked `/api/generate` and `/api/result/{task_id}` to use a unified async task envelope:
  - `pending`
  - `running`
  - `completed`
  - `failed`
  - `cancelled`
- Added AI Lab modes:
  - `compose_route`: recomposes a route from the current board's existing holds using the A* solver.
  - `review_route`: validates the current route and returns suggestions without mutating the board.
- Preserved the existing board persistence paths while saving full frontend board metadata:
  - `/api/save-board`
  - `/api/my-boards`
  - `/api/my-boards/{saved_id}`
- Kept legacy recipe-style generation compatible through the old `RouteRequest` payload path.
- Updated the frontend AI Lab to send mode, current board, and user requirements.
- Updated frontend polling to read the new result envelope.
- Added explicit Vite HTML input to avoid the Vite 8/Rolldown Windows Chinese-path build issue.
- Removed generated tracked `__pycache__` files from the workspace; `.gitignore` already prevents new ones.

## Verification

- `python -m py_compile` passed for backend entrypoint, agent modules, and core modules.
- FastAPI TestClient health/basic route checks passed:
  - `/api/health`
  - `/api/holds/mapping`
  - `/api/holds/vectors`
  - `/api/my-boards`
- Contract regression passed:
  - saves a new-style board without losing `board_spec` and `tags`
  - lists the saved board with those fields intact
  - `review_route` returns a completed task envelope
  - `compose_route` returns a completed task envelope
- `npm.cmd run build` passed after the Vite config change.

## Notes

- `python-multipart` is still not installed in the current local Python environment. The backend now imports and starts without it, but image upload requires installing `backend/requirements.txt`.
- Git commit/staging was intentionally not performed.
