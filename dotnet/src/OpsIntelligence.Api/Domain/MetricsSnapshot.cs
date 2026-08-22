namespace OpsIntelligence.Api.Domain;

public sealed record MetricsSnapshot(
    long Events,
    long Incidents,
    long Actions,
    long QueuedActions,
    long SucceededActions,
    long RetryActions,
    long FailedActions,
    long RetryAttempts,
    long PermanentFailures,
    long CooldownSuppressions,
    long AuditEntries);
