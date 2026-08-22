using OpsIntelligence.Api.Domain;

namespace OpsIntelligence.Api.Services;

public sealed class SyntheticActionExecutor
{
    public ActionExecutionResult Execute(QueuedAction action, int attempt)
    {
        return action.ExecutorMode switch
        {
            ExecutorModes.PermanentFailure => ActionExecutionResult.PermanentFailure("Synthetic permanent failure."),
            ExecutorModes.TransientThenSuccess when attempt == 1 => ActionExecutionResult.TransientFailure("Synthetic transient failure."),
            _ => ActionExecutionResult.Success()
        };
    }
}

public enum ActionExecutionKind
{
    Success,
    TransientFailure,
    PermanentFailure
}

public sealed record ActionExecutionResult(ActionExecutionKind Kind, string Message)
{
    public static ActionExecutionResult Success() => new(ActionExecutionKind.Success, "ok");
    public static ActionExecutionResult TransientFailure(string message) => new(ActionExecutionKind.TransientFailure, message);
    public static ActionExecutionResult PermanentFailure(string message) => new(ActionExecutionKind.PermanentFailure, message);
}
