namespace OpsIntelligence.Api.Domain;

public static class SyntheticFixtureFactory
{
    public static SyntheticEventRequest Create(int index, string runId)
    {
        var duplicatePreviousCritical = index > 0 && index % 20 == 1;
        var assetIndex = duplicatePreviousCritical ? index - 1 : index;
        var severity = (index % 10) switch
        {
            0 or 1 => 92,
            2 or 3 => 67,
            _ => 18
        };
        var category = severity >= 80
            ? "offline"
            : severity >= 50
                ? "degraded"
                : "heartbeat";
        var executorMode = index % 41 == 0
            ? ExecutorModes.TransientThenSuccess
            : ExecutorModes.Success;

        return new SyntheticEventRequest
        {
            Source = "synthetic-benchmark",
            AssetId = $"SYN-{runId}-{assetIndex:D6}",
            Category = category,
            Severity = severity,
            Message = $"Synthetic {category} event #{index:D6}",
            ExecutorMode = executorMode
        };
    }
}
