# GPT-5 Reasoning — System Instruction Best Practices

GPT-5 Reasoning is OpenAI's most capable deep-reasoning model in Copilot Studio (GA since December 2025, replacing o3). It uses internal chain-of-thought reasoning before responding, handling doctoral-level analytical, scientific, and logical tasks. Like all reasoning models, instructions must be goal-oriented and output-focused — not process-directive.

> **Rate:** Premium &nbsp;|&nbsp; **Context:** 400 K tokens &nbsp;|&nbsp; **Temperature:** not available (reasoning models use fixed sampling)

---

## Key Principle: Define Goals and Output — Let the Model Reason

GPT-5 Reasoning contains its own sophisticated problem-solving process. Directing it step-by-step wastes token budget and may degrade output quality.

| ❌ Avoid | ✅ Use Instead |
|---|---|
| "Think step by step" | "Provide a thorough analysis covering A, B, and C" |
| "First identify X, then consider Y" | "Your response must address X and Y, citing all sources" |
| "Reason carefully before responding" | "Be precise, comprehensive, and cite every claim" |
| "Chain of thought:" | "Format your response as follows:" |

---

## 1. Define Precise Output Specifications

GPT-5 Reasoning reliably follows detailed output schemas. Use them for complex structured tasks.

```
Analyse each contract clause as follows:
- Clause title: [name]
- Category: [obligation | limitation | termination | warranty | other]
- Key obligation: [1 sentence]
- Risk if breached: [low | medium | high]
- Applies to: [buyer | seller | both]
- Source: [document name, section]
```

---

## 2. Strict Grounding Rules (Critical for Private Data)

GPT-5 Reasoning has the broadest training knowledge of all Copilot Studio models. Grounding rules are **essential** to prevent answers from general knowledge contaminating private-data queries.

```
## Grounding Rules (highest priority — override all other instructions)
Answer exclusively from the documents and search results provided in context.
Every factual claim must be traceable to a specific source document.
Do not use general training knowledge unless it directly supports a claim in the provided sources.
If the information is not present in the grounding data, state: "Not found in available sources."
```

---

## 3. Self-Validation for High-Stakes Outputs

GPT-5 Reasoning can verify its own output. For regulated domains, use this to enforce compliance.

```
Before producing your final response, verify:
1. Every factual claim cites a specific source document and section.
2. No information was inferred beyond what the sources explicitly state.
3. The output format matches the required structure exactly.
4. If any constraint cannot be met, explain why before responding.
```

---

## 4. Persona and Authority Level

Be explicit about audience, domain authority, and output limitations for regulated agents.

```
You are a compliance AI assistant for the [Your Organisation] Legal Team.
Audience: internal legal professionals; assume familiarity with legal terminology.
Every response must include a source citation.
Append to all responses: "This is AI-generated information, not formal legal advice."
```

---

## 5. Scope and Escalation

```
You operate exclusively within [defined domain].
Do not answer questions outside this domain; redirect to [contact / channel].
If a question cannot be answered from available sources, state that explicitly.
Never speculate, extrapolate, or assume unstated context.
```

---

## 6. Temperature is Unavailable

GPT-5 Reasoning does not support the temperature setting. It uses a fixed sampling approach tuned for reasoning fidelity. You cannot increase or decrease response creativity via this control — use explicit output scope and format instructions instead.

---

## 7. Recommended Instruction Lengths

| Use Case | Target Length |
|---|---|
| Analytical / legal / financial agent | 300–3,000 chars |
| Complex knowledge agent with strict output | 1,000–10,000 chars |
| Multi-constraint enterprise agent | 2,000–20,000 chars |
| Maximum practical | 50,000 chars (400 K token context) |

---

## 8. Common Mistakes

- **Directing reasoning steps:** GPT-5 Reasoning already performs deep chain-of-thought — don't repeat it; it is counter-productive.
- **Missing grounding rules:** This model's broad training knowledge makes unconstrained grounding dangerous for private-data agents.
- **No output schema on structured tasks:** Define the expected format explicitly; the model handles the reasoning, not the presentation.
- **Deploying in production without evaluation:** This model offers experimental-adjacent power — run evaluations before full rollout.
- **No safety disclaimers for regulated domains:** Legal, medical, and financial agents must always include appropriate caveats.
