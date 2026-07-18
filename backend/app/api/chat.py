from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.agent.campus_map import ORIGIN_SELECT_LABELS
from app.api.dependencies import get_agent, get_current_user, get_thread_service
from app.models.auth import User
from app.models.chat import ChatRequest, ThreadRenameRequest
from app.services.threads import ThreadService

router = APIRouter(tags=["chat"])

ASK_ORIGIN_HISTORY_SUMMARY = "（現在地の選択をお願いしました）"
CLARIFICATION_HISTORY_PREFIX = "（確認質問）"


def _sanitize_agent_history(messages: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    for message in messages:
        agent_message = dict(message)
        map_payload = message.get("map")
        if (
            message.get("role") == "assistant"
            and isinstance(map_payload, dict)
            and map_payload.get("mode") == "ask_origin"
        ):
            agent_message["content"] = ASK_ORIGIN_HISTORY_SUMMARY
        metadata = message.get("metadata")
        if (
            message.get("role") == "assistant"
            and isinstance(metadata, dict)
            and metadata.get("kind") == "clarification"
        ):
            agent_message["content"] = (
                f"{CLARIFICATION_HISTORY_PREFIX}{str(message.get('content') or '').strip()}"
            )
        sanitized.append(agent_message)
    return sanitized


@router.post("/api/chat")
async def chat(
    payload: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    thread_service: Annotated[ThreadService, Depends(get_thread_service)],
    agent: Annotated[object, Depends(get_agent)],
) -> StreamingResponse:
    question = payload.message
    user_map_payload = None
    if payload.origin_node is not None:
        origin_label = ORIGIN_SELECT_LABELS[payload.origin_node]
        question = f"現在地は{origin_label}です。{payload.message}"
        user_map_payload = {
            "mode": "origin_select",
            "origin": {"node": payload.origin_node, "label": origin_label},
        }
    thread_id = payload.thread_id

    ensured_thread_id = thread_service.ensure_thread(user, thread_id, question)
    history = _sanitize_agent_history(
        thread_service.get_recent_messages(ensured_thread_id, limit=8)
    )
    thread_service.add_message(
        ensured_thread_id,
        "user",
        question,
        map_payload=user_map_payload,
    )
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
                    metadata = None
                    consume_metadata = getattr(agent, "consume_message_metadata", None)
                    if callable(consume_metadata):
                        metadata = consume_metadata(assistant_message_id)
                    if "kind" not in data:
                        data = {
                            **data,
                            "kind": "clarification"
                            if (metadata or {}).get("kind") == "clarification"
                            else None,
                        }
                    if metadata is None and data.get("kind") == "clarification":
                        metadata = {"kind": "clarification"}
                    thread_service.add_message(
                        ensured_thread_id,
                        "assistant",
                        "".join(answer_parts),
                        sources=data.get("sources", []),
                        map_payload=map_payload,
                        metadata=metadata,
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
