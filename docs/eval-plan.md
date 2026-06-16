# Evaluation Plan

## Component Evaluation

- Retrieval recall@k: whether supplier documents containing required evidence are returned.
- Citation hit rate: whether report claims include source snippets that support them.
- Tool success rate: whether tool calls return structured data and trace metadata.

## Trajectory Evaluation

- Planner includes supplier profile, compliance, delivery capability, and negative news.
- Critic detects missing dimensions.
- Graph loops to retrieval when evidence is missing and iteration budget remains.
- Writer rejects suppliers with sanctions or blacklist evidence.

## End-to-End Evaluation

Golden cases should include:

- Low-risk supplier with certifications and delivery evidence.
- Restricted supplier that must be rejected.
- Supplier with missing compliance evidence that requires conditional recommendation.
