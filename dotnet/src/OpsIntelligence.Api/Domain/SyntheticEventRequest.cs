namespace OpsIntelligence.Api.Domain;

public sealed class SyntheticEventRequest
{
    public string Source { get; init; } = "synthetic-monitor";
    public string AssetId { get; init; } = string.Empty;
    public string Category { get; init; } = "health";
    public int Severity { get; init; }
    public string Message { get; init; } = string.Empty;
    public string? ExecutorMode { get; init; }
    public DateTimeOffset? OccurredAt { get; init; }
}
