using OpsIntelligence.Api.Domain;

namespace OpsIntelligence.Api.Services;

public sealed class RuleEvaluator
{
    public RuleDecision Evaluate(OperationEvent operationEvent)
    {
        if (operationEvent.Severity >= 80 || operationEvent.Category is "offline" or "critical")
        {
            return new RuleDecision(true, true, "collect_diagnostics");
        }

        if (operationEvent.Severity >= 50 || operationEvent.Category is "degraded" or "warning")
        {
            return new RuleDecision(true, false, "none");
        }

        return new RuleDecision(false, false, "none");
    }
}

public sealed record RuleDecision(bool CreateIncident, bool QueueAction, string ActionType);
