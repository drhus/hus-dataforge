"""packages.api — kept import-light so engine/cli code can pull db, settings,
and queue helpers without dragging in the FastAPI app and creating circular
imports (api.app → routers → jobs_runner → engine → api → app)."""
