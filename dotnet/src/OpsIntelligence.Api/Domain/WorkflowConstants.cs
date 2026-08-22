namespace OpsIntelligence.Api.Domain;

public static class ActionStatuses
{
    public const string Queued = "queued";
    public const string Retry = "retry";
    public const string Succeeded = "succeeded";
    public const string FailedPermanent = "failed_permanent";
    public const string FailedExhausted = "failed_exhausted";
}

public static class ExecutorModes
{
    public const string Success = "success";
    public const string TransientThenSuccess = "transient_then_success";
    public const string PermanentFailure = "permanent_failure";
}

public static class IncidentStatuses
{
    public const string Open = "open";
}

public static class AuditEvents
{
    public const string EventReceived = "EVENT_RECEIVED";
    public const string NormalEventRecorded = "NORMAL_EVENT_RECORDED";
    public const string IncidentCreated = "INCIDENT_CREATED";
    public const string ActionQueued = "ACTION_QUEUED";
    public const string CooldownSuppressed = "COOLDOWN_SUPPRESSED";
    public const string ActionSucceeded = "ACTION_SUCCEEDED";
    public const string ActionTransientFailure = "ACTION_TRANSIENT_FAILURE";
    public const string ActionPermanentFailure = "ACTION_PERMANENT_FAILURE";
    public const string ActionRetryExhausted = "ACTION_RETRY_EXHAUSTED";
}
