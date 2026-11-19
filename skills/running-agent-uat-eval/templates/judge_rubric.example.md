<!-- Domain-specific rules injected into the LLM-as-a-Judge prompt.
     Keep this focused on project-specific constraints, citation conventions,
     acceptable refusal phrasing, and known edge cases. -->

- **Scope & Refusal**: Out-of-scope requests (outside legal/compliance policies) must use the agent's standard refusal wording without fabricating answers.
- **Citations**: Internal policy answers must cite the exact document title and clause/section visible in retrieved sources; never invent page numbers or intranet navigation paths.
- **No Ungrounded Extrapolation**: When a policy does not specify a numeric threshold or deadline, stating the general rule and referring the user to Legal/Compliance is a `PASS`; fabricating a date or figure is a `FAIL`.
- **Language Matching**: Responses must match the user's language/dialect unless a specific output language is requested.
