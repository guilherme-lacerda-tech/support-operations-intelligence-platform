namespace OpsIntelligence.Api.Domain;

public sealed record OperationEvent(
    string Id,
    string Source,
    string AssetId,
    string Category,
    int Severity,
    string Message,
    string ExecutorMode,
    DateTimeOffset OccurredAt,
    DateTimeOffset CreatedAt);
