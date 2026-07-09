from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.domain.schemas import RetryTaskResponse, TaskListResponse, TaskRunResponse

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(request: Request) -> TaskListResponse:
    tasks = request.app.state.application.orchestrator.list_tasks()
    return TaskListResponse(items=[
        TaskRunResponse(
            task_id=task.task_id,
            task_type=task.task_type,
            requester=task.requester,
            chat_id=task.chat_id,
            message_id=task.message_id,
            status=task.status,
            current_stage=task.current_stage,
            summary=task.summary,
            doc_url=task.doc_url,
        )
        for task in tasks
    ])


@router.get("/tasks/{task_id}", response_model=TaskRunResponse)
async def get_task(task_id: str, request: Request) -> TaskRunResponse:
    try:
        task = request.app.state.application.orchestrator.require_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskRunResponse(
        task_id=task.task_id,
        task_type=task.task_type,
        requester=task.requester,
        chat_id=task.chat_id,
        message_id=task.message_id,
        status=task.status,
        current_stage=task.current_stage,
        summary=task.summary,
        doc_url=task.doc_url,
    )


@router.post("/tasks/{task_id}/retry", response_model=RetryTaskResponse)
async def retry_task(task_id: str, request: Request) -> RetryTaskResponse:
    try:
        task = request.app.state.application.orchestrator.retry_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RetryTaskResponse(
        task_id=task.task_id,
        status=task.status,
        current_stage=task.current_stage,
        summary=task.summary,
    )


@router.post("/tasks/{task_id}/cancel", response_model=RetryTaskResponse)
async def cancel_task(task_id: str, request: Request) -> RetryTaskResponse:
    try:
        task = request.app.state.application.orchestrator.cancel_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RetryTaskResponse(
        task_id=task.task_id,
        status=task.status,
        current_stage=task.current_stage,
        summary=task.summary,
    )
