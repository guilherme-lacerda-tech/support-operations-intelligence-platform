using System.Threading.Channels;

namespace OpsIntelligence.Api.Services;

public interface IActionSignalQueue
{
    ValueTask SignalAsync(string actionId, CancellationToken cancellationToken = default);
    Task WaitForSignalOrDelayAsync(TimeSpan delay, CancellationToken cancellationToken = default);
}

public sealed class ChannelActionSignalQueue : IActionSignalQueue
{
    private readonly Channel<string> _channel = Channel.CreateUnbounded<string>(new UnboundedChannelOptions
    {
        SingleReader = true,
        SingleWriter = false
    });

    public ValueTask SignalAsync(string actionId, CancellationToken cancellationToken = default) =>
        _channel.Writer.WriteAsync(actionId, cancellationToken);

    public async Task WaitForSignalOrDelayAsync(TimeSpan delay, CancellationToken cancellationToken = default)
    {
        var delayTask = Task.Delay(delay, cancellationToken);
        var signalTask = _channel.Reader.WaitToReadAsync(cancellationToken).AsTask();
        var completed = await Task.WhenAny(delayTask, signalTask);

        if (completed == signalTask && await signalTask)
        {
            while (_channel.Reader.TryRead(out _))
            {
            }
        }
    }
}
