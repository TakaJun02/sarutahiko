from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent, get_current_user, get_thread_service
from app.models.auth import User
from app.models.chat import ChatRequest, ThreadRenameRequest
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
    history = thread_service.get_recent_messages(ensured_thread_id, limit=8)
    thread_service.add_message(ensured_thread_id, "user", question)
    assistant_message_id = str(uuid.uuid4())

    async def event_stream():
        answer_parts: list[str] = []
        map_payload: dict | None = None
        try:
            async for event, data in agent.stream(question, user, ensured_thread_id, assistant_message_id, history=history):
                if event == "token":
                    answer_parts.append(data["text"])
                if event == "map":
                    map_payload = data
                if event == "done":
                    thread_service.add_message(
                        ensured_thread_id,
                        "assistant",
                        "".join(answer_parts),
                        sources=data.get("sources", []),
                        map_payload=map_payload,
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


@router.get("/api/threads")
async def list_threads(
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
) -> dict:
    return {"threads": thread_service.list_threads(user)}


@router.get("/api/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
) -> dict:
    return thread_service.get_thread(user, thread_id)


@router.patch("/api/threads/{thread_id}")
async def rename_thread(
    thread_id: str,
    payload: ThreadRenameRequest,
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
) -> dict:
    return {"thread": thread_service.rename_thread(user, thread_id, payload.title)}


@router.delete("/api/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str,
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
) -> Response:
    thread_service.delete_thread(user, thread_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
