namespace OpsIntelligence.Api.Domain;

public sealed record Incident(
    string Id,
    string EventId,
    string AssetId,
    string Category,
    int Severity,
    string Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);
