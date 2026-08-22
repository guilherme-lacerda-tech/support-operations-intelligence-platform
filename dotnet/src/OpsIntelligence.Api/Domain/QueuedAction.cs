namespace OpsIntelligence.Api.Domain;

public sealed record QueuedAction(
    string Id,
    string IncidentId,
    string AssetId,
    string ActionType,
    string ExecutorMode,
    string Status,
    int Attempts,
    int MaxAttempts,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    DateTimeOffset NextAttemptAt,
    string? LastError);
