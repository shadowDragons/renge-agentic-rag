from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps.auth import require_permissions
from app.db.session import get_db
from app.repositories.assistants import AssistantRepository
from app.schemas.evaluation import (
    EvaluationDatasetSummary,
    EvaluationRunItemSummary,
    EvaluationRunRequest,
    EvaluationRunResponse,
)
from app.schemas.system import (
    SystemMaintenanceRequest,
    SystemMaintenanceResult,
    SystemOverview,
)
from app.services.evaluation import EvaluationService
from app.services.system_overview import SystemOverviewService

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(require_permissions("system:read"))],
)

@router.get("/overview", response_model=SystemOverview)
async def overview(
    db: DBSession = Depends(get_db),
) -> SystemOverview:
    return SystemOverviewService(db).build_overview()


@router.post(
    "/maintenance/run",
    response_model=SystemMaintenanceResult,
    dependencies=[Depends(require_permissions("system:write"))],
)
async def run_maintenance(
    payload: SystemMaintenanceRequest,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
) -> SystemMaintenanceResult:
    return SystemOverviewService(db).run_maintenance(payload, background_tasks)


@router.post(
    "/evaluations/run",
    response_model=EvaluationRunResponse,
    dependencies=[Depends(require_permissions("system:write"))],
)
async def run_evaluation(
    payload: EvaluationRunRequest,
    db: DBSession = Depends(get_db),
) -> EvaluationRunResponse:
    assistant = AssistantRepository(db).get(payload.assistant_id)
    if assistant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="助理不存在。",
        )
    evaluation_service = EvaluationService()
    dataset_key = payload.dataset_key.strip().lower()
    try:
        if payload.dataset_path.strip():
            dataset_path = payload.dataset_path.strip()
            dataset_items = evaluation_service.load_dataset(dataset_path)
        else:
            dataset_path = evaluation_service.resolve_dataset_path(dataset_key)
            dataset_items = evaluation_service.load_named_dataset(dataset_key)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的 dataset_key：{payload.dataset_key}",
        ) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"加载评测数据集失败：{exc}",
        ) from exc

    result = evaluation_service.run_dataset_for_assistant(
        assistant=assistant,
        dataset_items=dataset_items,
        dataset_path=dataset_path,
        limit=payload.limit,
        top_k=payload.top_k,
        write_scores_to_langfuse=payload.write_scores_to_langfuse,
    )
    return EvaluationRunResponse(
        run_id=result.run_id,
        assistant_id=result.assistant_id,
        assistant_name=result.assistant_name,
        dataset_key=dataset_key,
        dataset_path=result.dataset_path,
        dataset_item_count=result.dataset_item_count,
        success_count=result.success_count,
        failure_count=result.failure_count,
        average_scores=result.average_scores,
        items=[
            EvaluationRunItemSummary(
                item_id=item.item_id,
                question=item.question,
                trace_id=item.trace_id,
                trace_url=item.trace_url,
                answer_preview=item.answer_preview,
                fallback_reason=item.fallback_reason,
                retrieval_count=item.retrieval_count,
                citation_count=item.citation_count,
                citation_files=item.citation_files,
                prompt_name=item.prompt_name,
                prompt_version=item.prompt_version,
                prompt_source=item.prompt_source,
                average_score=item.average_score,
                scores=item.scores,
                error=item.error,
            )
            for item in result.item_results
        ],
    )


@router.get(
    "/evaluations/datasets",
    response_model=list[EvaluationDatasetSummary],
)
async def list_evaluation_datasets() -> list[EvaluationDatasetSummary]:
    service = EvaluationService()
    return [
        EvaluationDatasetSummary(
            key=definition.key,
            label=definition.label,
            description=definition.description,
            path=str(definition.path),
        )
        for definition in service.dataset_registry.list_definitions()
    ]
