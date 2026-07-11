from __future__ import annotations

_PROVIDER = None


def configure_tracing(exporter=None, endpoint: str = "http://localhost:6006/v1/traces"):
    """建 OTel TracerProvider 并注册 exporter。幂等：已配置则原样返回、不覆盖。"""
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint)  # 仅本地 Phoenix，绝不指远程
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _PROVIDER = provider
    return provider


def get_tracer():
    """未配置 → None（调用方据此透传、零开销、也不导入 otel）。"""
    if _PROVIDER is None:
        return None
    from opentelemetry import trace

    return trace.get_tracer("deepresearch_agent")


def reset_tracing() -> None:
    """清全局，测试用，避免跨用例串。"""
    global _PROVIDER
    _PROVIDER = None


def traced_node(name: str, node_fn, attr_fn=None):
    """图层节点包装器：开 span → 跑节点 → 从返回值抽属性 → 关 span；未配置则透传。"""

    def wrapped(state):
        tracer = get_tracer()
        if tracer is None:
            return node_fn(state)
        with tracer.start_as_current_span(name) as span:
            result = node_fn(state)
            if attr_fn is not None:
                for key, value in attr_fn(result).items():
                    if value is not None:
                        span.set_attribute(key, value)
            return result

    return wrapped
