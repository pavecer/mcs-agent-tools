# Claude Sonnet 4.5 — System Instruction Best Practices

Claude Sonnet 4.5 is an external AI model from Anthropic, available in Copilot Studio as an experimental model. It offers strong conversational quality, nuanced writing, and accurate instruction adherence with a 200 K-token context window. As an external (non-Microsoft) model, it is subject to Anthropic's usage terms and data handling policies.

> **Rate:** Standard &nbsp;|&nbsp; **Context:** 200 K tokens &nbsp;|&nbsp; **Status:** ⚠️ Experimental — subject to availability and preview terms.  
> **External model:** Content moderation controls are not available. Data handling follows Anthropic terms.  
> Requires **Enable External Models** to be enabled in the Power Platform admin centre.

---

## Key Differences from GPT Models

| Aspect | Claude Sonnet 4.5 | GPT-4.1 / GPT-5 Chat |
|---|---|---|
| Provider | Anthropic (external) | Microsoft (managed) |
| Content moderation control | Not available | Available |
| Data residency | Anthropic infrastructure | Azure-hosted |
| Prompt style | Responds well to clear role + XML-like structure | Markdown-structured instructions |
| Strengths | Nuanced writing, refusals, long-context recall | Broad instruction adherence, tool use |

---

## 1. System Prompt Structure

Claude models respond strongly to explicit role framing followed by structured task sections. Use XML-like headers or clear Markdown headings for distinct sections.

```
You are CustomerBot, a friendly customer support assistant for [Your Organisation].

## Role
Help customers with product questions, order tracking, returns, and general account enquiries.

## Scope
You only answer questions related to [Your Organisation] products and services.
For anything outside this scope, say: "That's outside what I can help with. Please contact [support channel]."

## Tone
Professional, warm, and concise. Avoid jargon.

## Knowledge Sources
Use only the documents and knowledge sources provided in context. Do not draw on general knowledge for product-specific facts.
```

---

## 2. Explicit Grounding Instructions

Claude Sonnet 4.5 has broad general knowledge. Explicit grounding is essential for private enterprise data.

```
## Grounding Rules
Answer only from the knowledge sources and documents provided in this conversation.
If an answer is not present in the provided sources, respond: "I don't have that specific information. Please contact [team/channel] for assistance."
Do not speculate or infer facts not present in the provided materials.
```

---

## 3. Refusal Behaviour

Claude models include built-in safety behaviours. Work with these rather than around them.

```
If a user request is outside your defined scope or violates safety guidelines, politely decline and redirect:
"I'm not able to help with that request. For [topic], please contact [appropriate contact]."
Do not explain safety policies in detail — simply decline and redirect.
```

---

## 4. Content Moderation Note

Content moderation controls in Copilot Studio are **not available** for external Anthropic models. Anthropic's own responsible AI policies apply instead. Ensure that:
- Your use case is appropriate for Anthropic's [usage policies](https://www.anthropic.com/legal/usage-policy).
- You have reviewed the Microsoft Product Terms covering Anthropic as a subprocessor (effective January 7, 2026).
- You do not process regulated personal data (GDPR, HIPAA, etc.) without reviewing Anthropic's DPA.

---

## 5. Handling the Experimental Stage

- **Not for production use.** Experimental models may have latency variability, availability gaps, and changed behaviour without notice.
- **Evaluate systematically** against GPT-5 Chat (GA) before considering for rollout.
- **Review Anthropic's terms** before processing sensitive or regulated data.
- **Enable with care:** Requires admin action in both Microsoft 365 admin centre and Power Platform admin centre.

---

## 6. Long-Context Usage

With 200 K tokens of context, Claude Sonnet 4.5 can hold very large knowledge sets. However:

```
## Context Instructions
Always prioritise information from the current conversation and provided documents over general knowledge.
When multiple documents address the same topic, cite all relevant sources.
If context is too long to process fully, focus on the most recently provided documents.
```

---

## 7. Recommended Instruction Lengths

| Use Case | Target Length |
|---|---|
| Focused conversational assistant | 300–2,000 chars |
| Knowledge-intensive enterprise agent | 500–8,000 chars |
| Complex long-context multi-domain agent | 1,000–15,000 chars |
| Maximum practical | 30,000 chars |

---

## 8. Common Mistakes

- **Ignoring Anthropic data terms:** External models have different data handling — review before deploying with customer or regulated data.
- **Assuming content moderation controls work:** This slider is disabled for external models — rely on Anthropic's built-in safety policies.
- **Over-engineering refusals:** Claude has strong built-in decline behaviour; excessive refusal instructions may create overly cautious agents.
- **Not testing scope boundaries:** Test explicitly that the agent refuses out-of-scope questions correctly.
