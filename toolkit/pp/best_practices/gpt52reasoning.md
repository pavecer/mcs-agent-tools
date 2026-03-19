# GPT-5.2 Reasoning — System Instruction Best Practices

GPT-5.2 Reasoning is an experimental next-generation deep-reasoning model in Copilot Studio. It provides the highest available reasoning depth in the Copilot Studio model catalogue. Like all reasoning models, it uses internal chain-of-thought — instructions must focus on goals, output requirements, and grounding constraints rather than directing the reasoning process.

> **Rate:** Premium &nbsp;|&nbsp; **Context:** 400 K tokens &nbsp;|&nbsp; **Status:** ⚠️ Experimental — subject to availability, performance variability, and preview terms. Do not use in production.
> **Temperature:** not available.

---

## Key Principle: Maximum Reasoning Depth — Minimal Process Direction

GPT-5.2 Reasoning exceeds GPT-5 Reasoning in analytical capability. The same principle applies: provide precise goals, constraints, and output schemas — the model handles reasoning internally.

| ❌ Avoid | ✅ Use Instead |
|---|---|
| "Reason through each step" | "Provide a complete analysis addressing X, Y, and Z" |
| "First, identify the problem…" | "Output must include: problem statement, root cause, evidence, recommendation" |
| "Think carefully before answering" | "Support every claim with a source citation" |

---

## 1. Detailed Output Schema

Put the model's superior reasoning to work with well-defined output structures.

```
For each risk identified in the provided documents:
- Risk title: [concise label]
- Category: [operational | financial | legal | reputational | technical]
- Likelihood: [low | medium | high]
- Impact: [low | medium | high]
- Mitigation: [1–2 sentences]
- Source: [document name, section, page if available]
```

---

## 2. Grounding Rules (Critical)

GPT-5.2 Reasoning has the most expansive training knowledge of any Copilot Studio model. Grounding rules are non-negotiable for enterprise deployments.

```
## Grounding Rules (override all other instructions)
Answer exclusively from the grounding data provided in context.
Every claim must reference a specific source document, section, or query result.
Do not use general training knowledge for factual statements.
If information is absent from grounding data, state: "Not found in available sources. Please consult [source / contact]."
```

---

## 3. Self-Validation

```
Before generating the final response, verify:
1. All factual claims cite a source.
2. No information was extrapolated beyond explicit source content.
3. Output structure matches the defined schema.
4. No sensitive or personal data is included beyond what is needed.
```

---

## 4. Persona, Authority, and Limitations

```
You are a strategic analysis AI assistant for the [Your Organisation] Strategy Team.
Audience: senior management and analysts.
You provide analysis and synthesis — not final recommendations.
Always include a caveat: "This analysis is AI-generated and should be reviewed by a qualified professional before informing decisions."
```

---

## 5. Handling the Experimental Stage

- **Production use is not recommended.** Experimental models carry latency, availability, and quality variability.
- **Evaluate systematically** against GPT-5 Reasoning (GA) before considering promotion.
- **Monitor latency** — deep reasoning models are inherently slower; this model may be slower still.
- **Premium cost applies** regardless of the experimental label.

---

## 6. Recommended Instruction Lengths

| Use Case | Target Length |
|---|---|
| Complex analytical assistant | 300–3,000 chars |
| Enterprise research / compliance agent | 1,000–10,000 chars |
| Multi-constraint expert knowledge agent | 2,000–20,000 chars |
| Maximum practical | 50,000 chars |

---

## 7. Common Mistakes

- **Treating it like a conversational model:** GPT-5.2 Reasoning is optimised for deep analysis — for general FAQ agents, use GPT-4.1 Mini.
- **Ignoring latency impact:** Reasoning takes time; alert end-users appropriately or use thinking indicators.
- **Missing grounding constraints:** This model's training breadth is its greatest risk for private-data agents.
- **No output schema on complex tasks:** Always define the expected format; reasoning ensures correctness, format instructions ensure usability.
