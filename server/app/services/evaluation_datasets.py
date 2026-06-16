from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvaluationDatasetDefinition:
    key: str
    path: Path
    label: str
    description: str


class EvaluationDatasetRegistry:
    ROOT = Path(__file__).resolve().parents[3] / "kb-file" / "evaluation_datasets"

    def __init__(self) -> None:
        self._definitions = {
            definition.key: definition
            for definition in (
                EvaluationDatasetDefinition(
                    key="hr_small",
                    path=self.ROOT / "hr_small_dataset.json",
                    label="HR Small",
                    description="员工与人事制度小样本数据集",
                ),
                EvaluationDatasetDefinition(
                    key="support_small",
                    path=self.ROOT / "support_small_dataset.json",
                    label="Support Small",
                    description="客户支持与 SOP 小样本数据集",
                ),
                EvaluationDatasetDefinition(
                    key="prd_small",
                    path=self.ROOT / "prd_small_dataset.json",
                    label="PRD Small",
                    description="产品研发与项目管理小样本数据集",
                ),
            )
        }

    def get(self, key: str) -> EvaluationDatasetDefinition | None:
        return self._definitions.get(str(key or "").strip().lower())

    def require(self, key: str) -> EvaluationDatasetDefinition:
        definition = self.get(key)
        if definition is None:
            raise KeyError(key)
        return definition

    def list_definitions(self) -> list[EvaluationDatasetDefinition]:
        return list(self._definitions.values())
