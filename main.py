import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from starlette.responses import JSONResponse

from config import settings
from middleware import TelegramAuthMiddleware
from workflow import interpret_step, router, model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_SGT = timezone(timedelta(hours=8))

# ─── EnrichedWorkflow ────────────────────────────────────────────────────────
# Subclasses Workflow to inject SYSTEM INFO (user identity, partner info, SGT time)
# into every message before the interpret agent sees it.
# This preserves the exact enriched prompt format that the LLM expects.

from agno.workflow.workflow import Workflow


class EnrichedWorkflow(Workflow):
    async def arun(self, input=None, *, user_id=None, **kwargs):
        if input and isinstance(input, str) and settings:
            enriched = self._enrich(input, user_id)
            return await super().arun(enriched, user_id=user_id, **kwargs)
        return await super().arun(input, user_id=user_id, **kwargs)

    @staticmethod
    def _enrich(text: str, user_id_str: str | None) -> str:
        current_sgt = datetime.now(_SGT).strftime("%Y-%m-%d %H:%M:%S")
        user_name = "Unknown"
        uid = 0
        if user_id_str:
            try:
                uid = int(user_id_str)
                user_name = settings.get_name_for_id(uid) or "Unknown"
            except (ValueError, TypeError):
                pass

        return (
            f"SYSTEM INFO:\n"
            f"Current Time (SGT): {current_sgt}\n"
            f"User Name: {user_name}\n"
            f"Telegram ID: {uid}\n"
            f"Partner 1 Name: {settings.partner_1_name} (ID: {settings.partner_1_id})\n"
            f"Partner 2 Name: {settings.partner_2_name} (ID: {settings.partner_2_id})\n\n"
            f"USER REQUEST:\n"
            f"{text}"
        )


# ─── Build the workflow ──────────────────────────────────────────────────────

enriched_workflow = None
if model:
    enriched_workflow = EnrichedWorkflow(
        name="Expense Tracker",
        steps=[interpret_step, router],
    )

# ─── Base FastAPI app (health check + auth middleware) ────────────────────────

base_app = FastAPI()
base_app.add_middleware(TelegramAuthMiddleware)


@base_app.get("/")
async def health_check():
    if not settings:
        return JSONResponse({"status": "error", "message": "Environment configuration missing"})
    return JSONResponse({"status": "ok", "message": "Bot is running and ready to receive webhooks."})


# ─── AgentOS + Telegram Interface ────────────────────────────────────────────

app = base_app  # fallback if AgentOS can't be initialized

if enriched_workflow and settings and settings.telegram_token:
    try:
        from agno.os.app import AgentOS
        from agno.os.interfaces.telegram import Telegram

        telegram_interface = Telegram(
            workflow=enriched_workflow,
            token=settings.telegram_token,
            streaming=False,
        )

        agent_os = AgentOS(
            name="Expense Tracker",
            workflows=[enriched_workflow],
            interfaces=[telegram_interface],
            base_app=base_app,
        )

        app = agent_os.get_app()
        logger.info("AgentOS initialized with Telegram interface.")
    except Exception as e:
        logger.error(f"Failed to initialize AgentOS: {e}", exc_info=True)
        logger.warning("Falling back to base FastAPI app (no Telegram interface).")
else:
    logger.warning("Workflow or Telegram token missing — running health-check-only mode.")


if __name__ == "__main__":
    import uvicorn

    port = settings.port if settings else int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
