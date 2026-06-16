import { defineStore } from "pinia";

import {
  fetchSystemOverview,
  runSystemEvaluation,
  runSystemMaintenance,
  type EvaluationRunRequest,
  type EvaluationRunResponse,
  type SystemMaintenanceRequest,
  type SystemMaintenanceResult,
  type SystemOverview,
} from "@/api/system";

interface SystemState {
  overview: SystemOverview | null;
  loadingOverview: boolean;
  runningMaintenance: boolean;
  runningEvaluation: boolean;
  overviewError: string | null;
  maintenanceError: string | null;
  evaluationError: string | null;
  lastMaintenanceResult: SystemMaintenanceResult | null;
  lastEvaluationResult: EvaluationRunResponse | null;
}

export const useSystemStore = defineStore("system", {
  state: (): SystemState => ({
    overview: null,
    loadingOverview: false,
    runningMaintenance: false,
    runningEvaluation: false,
    overviewError: null,
    maintenanceError: null,
    evaluationError: null,
    lastMaintenanceResult: null,
    lastEvaluationResult: null,
  }),
  actions: {
    async loadOverview() {
      this.loadingOverview = true;
      this.overviewError = null;

      try {
        this.overview = await fetchSystemOverview();
      } catch (error) {
        this.overviewError =
          error instanceof Error ? error.message : "系统概览加载失败。";
      } finally {
        this.loadingOverview = false;
      }
    },
    async runMaintenance(payload: SystemMaintenanceRequest) {
      this.runningMaintenance = true;
      this.maintenanceError = null;
      try {
        this.lastMaintenanceResult = await runSystemMaintenance(payload);
        return this.lastMaintenanceResult;
      } catch (error) {
        this.maintenanceError =
          error instanceof Error ? error.message : "系统维护执行失败。";
        throw error;
      } finally {
        this.runningMaintenance = false;
      }
    },
    async runEvaluation(payload: EvaluationRunRequest) {
      this.runningEvaluation = true;
      this.evaluationError = null;
      try {
        this.lastEvaluationResult = await runSystemEvaluation(payload);
        return this.lastEvaluationResult;
      } catch (error) {
        this.evaluationError =
          error instanceof Error ? error.message : "离线评测执行失败。";
        throw error;
      } finally {
        this.runningEvaluation = false;
      }
    },
  },
});
