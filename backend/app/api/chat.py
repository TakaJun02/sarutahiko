from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent, get_current_user, get_thread_service
from app.models.auth import User
from app.models.chat import ChatRequest
from app.services.threads import ThreadService

router = APIRouter(tags=["chat"])


@router.post("/api/chat")
async def chat(
    payload: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
    agent: Annotated[object, Depends(get_agent)],
) -> StreamingResponse:
    question = payload.message
    thread_id = payload.thread_id

    ensured_thread_id = thread_service.ensure_thread(user, thread_id, question)
    history = thread_service.get_recent_messages(ensured_thread_id, limit=6)
    thread_service.add_message(ensured_thread_id, "user", question)
    assistant_message_id = str(uuid.uuid4())

    async def event_stream():
        answer_parts: list[str] = []
        try:
            async for event, data in agent.stream(question, user, ensured_thread_id, assistant_message_id, history=history):
                if event == "token":
                    answer_parts.append(data["text"])
                if event == "done":
                    thread_service.add_message(
                        ensured_thread_id,
                        "assistant",
                        "".join(answer_parts),
                        sources=data.get("sources", []),
                        message_id=assistant_message_id,
                    )
                yield agent.format_sse(event, data)
        except Exception as exc:
            yield agent.format_sse("error", {"message": "回答生成中にエラーが発生しました。"})
            raise exc

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
) -> dict:
    return thread_service.get_thread(user, thread_id)
