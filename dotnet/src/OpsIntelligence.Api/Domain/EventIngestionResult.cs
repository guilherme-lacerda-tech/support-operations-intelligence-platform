namespace OpsIntelligence.Api.Domain;

public sealed record EventIngestionResult(
    string EventId,
    string Decision,
    string? IncidentId,
    string? ActionId,
    bool Suppressed);
