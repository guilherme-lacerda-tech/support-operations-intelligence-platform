namespace OpsIntelligence.Api.Domain;

public sealed record ActionProcessingBatchResult(
    int Processed,
    int Succeeded,
    int Retried,
    int Failed,
    int Skipped);
