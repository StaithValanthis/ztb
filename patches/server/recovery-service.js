import { and, asc, desc, eq, gt, gte, inArray, isNull, notInArray, sql } from "drizzle-orm";
import { DEFAULT_ISSUE_GRAPH_LIVENESS_AUTO_RECOVERY_LOOKBACK_HOURS, MAX_ISSUE_GRAPH_LIVENESS_AUTO_RECOVERY_LOOKBACK_HOURS, MIN_ISSUE_GRAPH_LIVENESS_AUTO_RECOVERY_LOOKBACK_HOURS, } from "@paperclipai/shared";
import { agents, agentWakeupRequests, approvals, activityLog, companies, heartbeatRunEvents, heartbeatRunWatchdogDecisions, heartbeatRuns, issueComments, issueApprovals, issueRecoveryActions, issueRelations, issueThreadInteractions, issues, } from "@paperclipai/db";
import { parseObject, asBoolean, asNumber } from "../../adapters/utils.js";
import { runningProcesses } from "../../adapters/index.js";
import { forbidden, notFound } from "../../errors.js";
import { logger } from "../../middleware/logger.js";
import { isPidAlive, isProcessGroupAlive, terminateLocalService } from "../local-service-supervisor.js";
import { redactCurrentUserText } from "../../log-redaction.js";
import { redactSensitiveText } from "../../redaction.js";
import { logActivity } from "../activity-log.js";
import { budgetService } from "../budgets.js";
import { instanceSettingsService } from "../instance-settings.js";
import { issueRecoveryActionService } from "../issue-recovery-actions.js";
import { issueTreeControlService } from "../issue-tree-control.js";
import { issueService } from "../issues.js";
import { getRunLogStore } from "../run-log-store.js";
import { DEFAULT_MAX_SUCCESSFUL_RUN_HANDOFF_ATTEMPTS, FINISH_SUCCESSFUL_RUN_HANDOFF_REASON, SUCCESSFUL_RUN_MISSING_STATE_REASON, buildSuccessfulRunHandoffExhaustedNotice, noticeMetadataReferencesRecoveryAction, } from "./successful-run-handoff.js";
import { RECOVERY_ORIGIN_KINDS, buildIssueGraphLivenessLeafKey, isStrandedIssueRecoveryOriginKind, parseIssueGraphLivenessIncidentKey, } from "./origins.js";
import { classifyIssueGraphLiveness, } from "./issue-graph-liveness.js";
import { recoveryAssigneeAdapterOverrides, withRecoveryModelProfileHint, } from "./model-profile-hint.js";
import { isAutomaticRecoverySuppressedByPauseHold } from "./pause-hold-guard.js";
const EXECUTION_PATH_HEARTBEAT_RUN_STATUSES = ["queued", "running", "scheduled_retry"];
const UNSUCCESSFUL_HEARTBEAT_RUN_TERMINAL_STATUSES = ["failed", "cancelled", "timed_out"];
export const ACTIVE_RUN_OUTPUT_SUSPICION_THRESHOLD_MS = 60 * 60 * 1000;
export const ACTIVE_RUN_OUTPUT_CRITICAL_THRESHOLD_MS = 4 * 60 * 60 * 1000;
export const ACTIVE_RUN_OUTPUT_CONTINUE_REARM_MS = 30 * 60 * 1000;
const ACTIVE_RUN_OUTPUT_EVIDENCE_TAIL_BYTES = 8 * 1024;
const STRANDED_ISSUE_RECOVERY_ORIGIN_KIND = RECOVERY_ORIGIN_KINDS.strandedIssueRecovery;
const STALE_ACTIVE_RUN_EVALUATION_ORIGIN_KIND = RECOVERY_ORIGIN_KINDS.staleActiveRunEvaluation;
const DEFERRED_WAKE_CONTEXT_KEY = "_paperclipWakeContext";
const SESSIONED_LOCAL_ADAPTERS = new Set([
    "claude_local",
    "codex_local",
    "cursor",
    "gemini_local",
    "hermes_local",
    "opencode_local",
    "pi_local",
]);
function readNonEmptyString(value) {
    return typeof value === "string" && value.trim().length > 0 ? value : null;
}
function summarizeRunFailureForIssueComment(run) {
    if (!run)
        return null;
    if (readNonEmptyString(run.error) || readNonEmptyString(run.errorCode)) {
        return " Latest retry failure details were withheld from the issue thread; inspect the linked run for evidence.";
    }
    return null;
}
function didAutomaticRecoveryFail(latestRun, expectedRetryReason) {
    if (!latestRun)
        return false;
    const latestContext = parseObject(latestRun.contextSnapshot);
    const latestRetryReason = readNonEmptyString(latestContext.retryReason);
    return latestRetryReason === expectedRetryReason &&
        UNSUCCESSFUL_HEARTBEAT_RUN_TERMINAL_STATUSES.includes(latestRun.status);
}
const TRANSIENT_INFRA_CONTINUATION_ERROR_CODES = new Set([
    "adapter_failed",
    "codex_transient_upstream",
    "claude_transient_upstream",
    "opencode_transient_upstream",
    "timeout",
]);
const NON_RETRYABLE_CONTINUATION_ERROR_CODES = new Set([
    "agent_not_invokable",
    "agent_not_found",
    "budget_blocked",
    "budget_exhausted",
    "issue_paused",
    "issue_dependencies_blocked",
]);
const CONTINUATION_RECOVERY_TRANSIENT_MAX_ATTEMPTS = 3;
const CONTINUATION_RECOVERY_DEFAULT_MAX_ATTEMPTS = 1;
const CONTINUATION_RECOVERY_TRANSIENT_BASE_BACKOFF_MS = 60_000;
function classifyContinuationFailure(latestRun) {
    const errorCode = readNonEmptyString(latestRun?.errorCode);
    if (errorCode && NON_RETRYABLE_CONTINUATION_ERROR_CODES.has(errorCode)) {
        return { kind: "non_retryable", maxAttempts: 0, baseBackoffMs: 0, errorCode };
    }
    if (errorCode && TRANSIENT_INFRA_CONTINUATION_ERROR_CODES.has(errorCode)) {
        return {
            kind: "transient_infra",
            maxAttempts: CONTINUATION_RECOVERY_TRANSIENT_MAX_ATTEMPTS,
            baseBackoffMs: CONTINUATION_RECOVERY_TRANSIENT_BASE_BACKOFF_MS,
            errorCode,
        };
    }
    return {
        kind: "default",
        maxAttempts: CONTINUATION_RECOVERY_DEFAULT_MAX_ATTEMPTS,
        baseBackoffMs: 0,
        errorCode,
    };
}
function successfulRunHandoffRecoveryEvidence(latestRun) {
    if (!latestRun)
        return null;
    const context = parseObject(latestRun.contextSnapshot);
    const wakeReason = readNonEmptyString(context.wakeReason);
    const handoffReason = readNonEmptyString(context.handoffReason);
    const isSuccessfulRunHandoff = wakeReason === FINISH_SUCCESSFUL_RUN_HANDOFF_REASON ||
        handoffReason === SUCCESSFUL_RUN_MISSING_STATE_REASON ||
        asBoolean(context.handoffRequired, false) === true;
    if (!isSuccessfulRunHandoff)
        return null;
    const handoffAttempt = asNumber(context.handoffAttempt, 1);
    const maxHandoffAttempts = asNumber(context.maxHandoffAttempts, DEFAULT_MAX_SUCCESSFUL_RUN_HANDOFF_ATTEMPTS);
    return {
        sourceRunId: readNonEmptyString(context.sourceRunId) ?? readNonEmptyString(context.resumeFromRunId),
        correctiveRunId: latestRun.id,
        missingDisposition: readNonEmptyString(context.missingDisposition) ?? "clear_next_step",
        handoffAttempt,
        maxHandoffAttempts,
    };
}
function isExhaustedSuccessfulRunHandoff(latestRun) {
    const evidence = successfulRunHandoffRecoveryEvidence(latestRun);
    if (!evidence)
