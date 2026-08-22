using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Domain;
using OpsIntelligence.Api.Persistence;

namespace OpsIntelligence.Api.Services;

public sealed class ActionProcessor
{
    private readonly SqliteOpsStore _store;
    private readonly SyntheticActionExecutor _executor;
    private readonly OpsProcessingOptions _options;
    private readonly TimeProvider _timeProvider;

    public ActionProcessor(
        SqliteOpsStore store,
        SyntheticActionExecutor executor,
        IOptions<OpsProcessingOptions> options,
        TimeProvider timeProvider)
    {
        _store = store;
        _executor = executor;
        _options = options.Value;
        _timeProvider = timeProvider;
    }

    public async Task<ActionProcessingBatchResult> ProcessPendingAsync(
        int limit,
        CancellationToken cancellationToken = default)
    {
        var now = _timeProvider.GetUtcNow();
        var actions = await _store.GetDueActionsAsync(limit, now, cancellationToken);
        var succeeded = 0;
        var retried = 0;
        var failed = 0;

        foreach (var action in actions)
        {
            var attempt = action.Attempts + 1;
            var outcome = _executor.Execute(action, attempt);
            var updatedAt = _timeProvider.GetUtcNow();

            if (outcome.Kind == ActionExecutionKind.Success)
            {
                await _store.UpdateActionAsync(action with
                {
                    Status = ActionStatuses.Succeeded,
                    Attempts = attempt,
                    UpdatedAt = updatedAt,
                    NextAttemptAt = updatedAt,
                    LastError = null
                }, cancellationToken);
                await _store.AddAuditAsync("action", action.Id, AuditEvents.ActionSucceeded, "Synthetic action succeeded.", updatedAt, cancellationToken);
                succeeded++;
                continue;
            }

            if (outcome.Kind == ActionExecutionKind.TransientFailure && attempt < action.MaxAttempts)
            {
                await _store.UpdateActionAsync(action with
                {
                    Status = ActionStatuses.Retry,
                    Attempts = attempt,
                    UpdatedAt = updatedAt,
                    NextAttemptAt = updatedAt.Add(_options.RetryDelay),
                    LastError = outcome.Message
                }, cancellationToken);
                await _store.AddAuditAsync("action", action.Id, AuditEvents.ActionTransientFailure, outcome.Message, updatedAt, cancellationToken);
                retried++;
                continue;
            }

            var finalStatus = outcome.Kind == ActionExecutionKind.PermanentFailure
                ? ActionStatuses.FailedPermanent
                : ActionStatuses.FailedExhausted;
            var finalAuditEvent = outcome.Kind == ActionExecutionKind.PermanentFailure
                ? AuditEvents.ActionPermanentFailure
                : AuditEvents.ActionRetryExhausted;
            await _store.UpdateActionAsync(action with
            {
                Status = finalStatus,
                Attempts = attempt,
                UpdatedAt = updatedAt,
                NextAttemptAt = updatedAt,
                LastError = outcome.Message
            }, cancellationToken);
            await _store.AddAuditAsync("action", action.Id, finalAuditEvent, outcome.Message, updatedAt, cancellationToken);
            failed++;
        }

        return new ActionProcessingBatchResult(actions.Count, succeeded, retried, failed, 0);
    }
}
