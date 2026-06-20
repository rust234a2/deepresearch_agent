# 评估计划（后置）

当前里程碑先交付基于预设数据的可用采购尽调 v1，暂不实现评估代码、golden cases、RAGAS 或 Phoenix 集成。

后续评估阶段按以下顺序实施：

1. 建立 golden cases，覆盖低风险、受限制、资料缺失、未知供应商和歧义供应商。
2. 增加确定性指标：推荐准确率、风险命中率、引用覆盖率、缺失数据处理率和检索召回率。
3. 使用 RAGAS 评估 RAG 检索与回答质量。
4. 使用 Phoenix 调试检索、工具调用和 Agent 轨迹。
5. 确定性指标稳定后，再考虑 LLM-as-judge。

评估必须复用 `deepresearch_agent.agents.graph.run_research`，不得建立第二条执行路径。
