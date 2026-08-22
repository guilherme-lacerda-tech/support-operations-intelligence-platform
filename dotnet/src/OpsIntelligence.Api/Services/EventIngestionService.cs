using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Domain;
using OpsIntelligence.Api.Persistence;

namespace OpsIntelligence.Api.Services;

public sealed class EventIngestionService
{
    private readonly SqliteOpsStore _store;
    private readonly RuleEvaluator _ruleEvaluator;
    private readonly IActionSignalQueue _queue;
    private readonly OpsProcessingOptions _options;
    private readonly TimeProvider _timeProvider;

    public EventIngestionService(
        SqliteOpsStore store,
        RuleEvaluator ruleEvaluator,
        IActionSignalQueue queue,
        IOptions<OpsProcessingOptions> options,
        TimeProvider timeProvider)
    {
        _store = store;
        _ruleEvaluator = ruleEvaluator;
        _queue = queue;
        _options = options.Value;
        _timeProvider = timeProvider;
    }

    public async Task<EventIngestionResult> IngestAsync(
        SyntheticEventRequest request,
        CancellationToken cancellationToken = default)
    {
        var now = _timeProvider.GetUtcNow();
        var normalized = Normalize(request, now);
        var decision = _ruleEvaluator.Evaluate(normalized);

        var result = await _store.RecordIngestionDecisionAsync(
            normalized,
            decision.CreateIncident,
            decision.QueueAction,
            decision.ActionType,
            _options.MaxActionAttempts,
            _options.Cooldown,
            now,
            cancellationToken);

        if (result.ActionId is not null)
        {
            await _queue.SignalAsync(result.ActionId, cancellationToken);
        }

        return result;
    }

    private static OperationEvent Normalize(SyntheticEventRequest request, DateTimeOffset now)
    {
        if (string.IsNullOrWhiteSpace(request.AssetId))
        {
            throw new ArgumentException("asset_id is required", nameof(request));
        }

        var source = string.IsNullOrWhiteSpace(request.Source) ? "synthetic-monitor" : request.Source.Trim();
        var category = string.IsNullOrWhiteSpace(request.Category) ? "health" : request.Category.Trim().ToLowerInvariant();
        var message = string.IsNullOrWhiteSpace(request.Message) ? "Synthetic event" : request.Message.Trim();
        var executorMode = NormalizeExecutorMode(request.ExecutorMode, message, category);

        return new OperationEvent(
            SqliteOpsStore.NewId("evt"),
            source,
            request.AssetId.Trim(),
            category,
            Math.Clamp(request.Severity, 0, 100),
            message,
            executorMode,
            request.OccurredAt ?? now,
            now);
    }

    private static string NormalizeExecutorMode(string? requestedMode, string message, string category)
    {
        var value = requestedMode?.Trim().ToLowerInvariant();
        if (value is ExecutorModes.Success or ExecutorModes.TransientThenSuccess or ExecutorModes.PermanentFailure)
        {
            return value;
        }

        var combined = $"{message} {category}".ToLowerInvariant();
        if (combined.Contains("permanent", StringComparison.Ordinal))
        {
            return ExecutorModes.PermanentFailure;
        }

        if (combined.Contains("transient", StringComparison.Ordinal))
        {
            return ExecutorModes.TransientThenSuccess;
        }

        return ExecutorModes.Success;
    }
}
