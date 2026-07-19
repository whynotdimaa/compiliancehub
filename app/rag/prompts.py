"""Prompts for the CRAG agent. Kept in one place so they are reviewable
as text, not scattered through control flow."""

GRADER_SYSTEM = (
    "You grade retrieved passages for relevance to a question. "
    "Reply ONLY with a JSON array of booleans, one per passage, in order — "
    "true if the passage helps answer the question. Example: [true, false, true]. "
    "No commentary."
)


def grader_user(question: str, passages: list[str]) -> str:
    blocks = "\n\n".join(f"[{i}] {p[:1500]}" for i, p in enumerate(passages, start=1))
    return f"Question: {question}\n\nPassages:\n{blocks}"


REWRITE_SYSTEM = (
    "You rewrite search queries for a compliance-document search engine. "
    "Expand acronyms, add synonyms for key terms, keep it one line. "
    "Reply ONLY with the rewritten query, nothing else."
)

ANSWER_SYSTEM = (
    "You are a compliance analyst. Answer the question using ONLY the numbered "
    "context blocks. Cite every claim with its block number like [1] or [2][3]. "
    "If the context does not contain the answer, say exactly what is missing — "
    "never invent facts, regulations or article numbers. Be concise."
)


def answer_user(question: str, blocks: list[str]) -> str:
    context = "\n\n".join(blocks) if blocks else "(no context available)"
    return f"Context:\n{context}\n\nQuestion: {question}"
