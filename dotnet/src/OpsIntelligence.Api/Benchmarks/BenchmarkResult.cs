namespace OpsIntelligence.Api.Benchmarks;

public sealed record BenchmarkResult(
    int RequestedEvents,
    int AcceptedEvents,
    int ProcessingErrors,
    long IncidentsCreated,
    long ActionsCreated,
    long CooldownSuppressions,
    double TotalMilliseconds,
    double EventsPerSecond,
    double CpuMilliseconds,
    double WorkingSetStartMb,
    double WorkingSetEndMb,
    string Notes);
