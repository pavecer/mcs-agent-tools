# Claude Opus 4.5 — System Instruction Best Practices

Claude Opus 4.5 is Anthropic's most capable model available in Copilot Studio, positioned in the Deep/Premium tier alongside GPT-5 reasoning. It excels at complex analysis, nuanced writing, multi-step reasoning, and sophisticated instruction following, with a 200 K-token context window. As an external (non-Microsoft) model it is subject to Anthropic's terms and data handling policies.

> **Rate:** Premium &nbsp;|&nbsp; **Context:** 200 K tokens &nbsp;|&nbsp; **Status:** ⚠️ Experimental — subject to availability and preview terms.
> **External model:** Content moderation controls are not available. Data handling follows Anthropic terms.
> Replaces Claude Opus 4.1 (retired February 2026). Requires **Enable External Models** in the Power Platform admin centre.

---

## Key Differences from GPT Reasoning Models

| Aspect | Claude Opus 4.5 | GPT-5 Reasoning |
|---|---|---|
| Provider | Anthropic (external) | Microsoft (managed) |
| Content moderation control | Not available | Available |
| Context window | 200 K tokens | 400 K tokens |
| Reasoning approach | Deep analytical reasoning | Chain-of-thought reasoning |
| Strengths | Writing quality, nuance, ethical care | Structured logic, math, code |

---

## 1. Goal-Oriented Instructions

Like all deep-reasoning models, Claude Opus 4.5 excels when given clear goals and output specifications rather than step-by-step process directions.

```
Analyse the provided contract documents and produce a risk summary. For each identified risk, provide:
- Risk title
- Risk category: [legal | financial | operational | reputational]
- Severity: [low | medium | high]
- Relevant clause (quoted verbatim or paraphrased closely)
- Recommended mitigation (1–2 sentences)
- Source document and section
```

---

## 2. Strict Grounding Rules

Claude Opus 4.5's extensive training knowledge requires explicit grounding for enterprise data agents.

```
## Grounding Rules (highest priority)
Answer exclusively from the documents and knowledge sources provided in this conversation.
Do not use general training knowledge for factual claims about [organisation] or its products, policies, or data.
Every factual claim must be traceable to a source document.
If information is not in the provided sources, state: "This information is not available in the provided sources."
```

---

## 3. Persona and Authority

Opus models respond well to clearly scoped personas with explicit authority and limitation statements.

```
You are an AI analysis assistant for the [Your Organisation] Strategy Team.
Audience: senior analysts and executives — assume domain expertise.
You provide structured analysis based on provided documents only.
You do not make final strategic recommendations — you inform human decision-makers.
Always caveat: "This output is AI-generated analysis. Decisions should be validated by qualified professionals."
```

---

## 4. Content Moderation Note

Content moderation controls in Copilot Studio are **not available** for external Anthropic models. Anthropic's own responsible AI policies govern outputs. Ensure:
- Your use case complies with Anthropic's [usage policy](https://www.anthropic.com/legal/usage-policy).
- You have reviewed the Microsoft Product Terms covering Anthropic as a subprocessor (effective January 7, 2026).
- Regulated or sensitive data (GDPR, HIPAA, etc.) is handled in accordance with Anthropic's Data Processing Addendum.

---

## 5. Self-Review Instruction

Claude Opus 4.5 supports meta-cognitive self-review similarly to GPT-5 reasoning models.

```
Before producing the final output, verify:
1. Every factual statement cites a source document.
2. No information was extrapolated beyond what the sources explicitly state.
3. The output structure matches the required schema.
4. Appropriate professional disclaimers are appended for regulated domains.
```

---

## 6. Handling the Experimental Stage

- **Not for production use** without extensive evaluation and stakeholder sign-off.
- **Compare against GPT-5 Reasoning (GA)** for your specific domain before committing to Claude Opus.
- **Premium cost applies.** Evaluate ROI relative to GPT-5 Chat or GPT-4.1 for lower-complexity use cases.
- **Review Anthropic data terms** before processing customer or regulated data.

---

## 7. Recommended Instruction Lengths

| Use Case | Target Length |
|---|---|
| Complex analytical / research agent | 300–3,000 chars |
| Enterprise legal / compliance agent | 1,000–10,000 chars |
| Multi-domain expert knowledge agent | 2,000–20,000 chars |
| Maximum practical | 40,000 chars (200 K token context) |

---

## 8. Common Mistakes

- **Selecting Opus over Sonnet without justification:** Claude Sonnet 4.5 handles most Standard-rate tasks; Opus is Premium — only upgrade if quality difference is measurable.
- **Ignoring Anthropic data terms:** External model data handling is separate from Microsoft's data residency commitments — review before deploying with regulated data.
- **Missing professional disclaimers:** For legal, medical, or financial agents, always append appropriate caveats regardless of model.
- **Treating "experimental" as "production preview":** Experimental = not for scaled production use; run full evaluations before any live rollout.
