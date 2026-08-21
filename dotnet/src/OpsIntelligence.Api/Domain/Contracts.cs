using System.Text.Json.Serialization;

namespace OpsIntelligence.Api.Domain;

public sealed record EventRequest(
    [property: JsonPropertyName("asset_id")] string AssetId,
    [property: JsonPropertyName("source")] string Source,
    [property: JsonPropertyName("category")] string Category,
    [property: JsonPropertyName("severity")] int Severity,
    [property: JsonPropertyName("occurred_at")] DateTimeOffset? OccurredAt,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("executor_mode")] string ExecutorMode = "success");

public sealed record ProcessResult(
    [property: JsonPropertyName("event_id")] long EventId,
    [property: JsonPropertyName("incident_id")] long? IncidentId,
    [property: JsonPropertyName("action_id")] long? ActionId,
    [property: JsonPropertyName("skipped_reason")] string? SkippedReason);

public sealed record IncidentRecord(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("asset_id")] string AssetId,
    [property: JsonPropertyName("event_id")] long EventId,
    [property: JsonPropertyName("category")] string Category,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("summary")] string Summary,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record ActionRecord(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("incident_id")] long IncidentId,
    [property: JsonPropertyName("action_type")] string ActionType,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("attempts")] int Attempts,
    [property: JsonPropertyName("detail")] string Detail,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record AuditRecord(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("event_type")] string EventType,
    [property: JsonPropertyName("entity_type")] string EntityType,
    [property: JsonPropertyName("entity_id")] long EntityId,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

public sealed record MetricsSnapshot(
    [property: JsonPropertyName("events")] int Events,
    [property: JsonPropertyName("incidents")] int Incidents,
    [property: JsonPropertyName("actions")] int Actions,
    [property: JsonPropertyName("audit_logs")] int AuditLogs,
    [property: JsonPropertyName("suppressions")] int Suppressions,
    [property: JsonPropertyName("queued_actions")] int QueuedActions,
    [property: JsonPropertyName("succeeded_actions")] int SucceededActions,
    [property: JsonPropertyName("failed_actions")] int FailedActions,
    [property: JsonPropertyName("retries")] int Retries);

public sealed record MaintenanceResult(
    [property: JsonPropertyName("processed")] int Processed,
    [property: JsonPropertyName("succeeded")] int Succeeded,
    [property: JsonPropertyName("failed")] int Failed);

public sealed record ResetResult([property: JsonPropertyName("deleted")] IReadOnlyDictionary<string, int> Deleted);
