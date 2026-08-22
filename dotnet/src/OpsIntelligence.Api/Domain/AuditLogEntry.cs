namespace OpsIntelligence.Api.Domain;

public sealed record AuditLogEntry(
    string Id,
    string EntityType,
    string EntityId,
    string EventType,
    string Message,
    DateTimeOffset CreatedAt);
