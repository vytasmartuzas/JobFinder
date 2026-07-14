"""CV tailoring — rewrite the *content* of a CV for a specific job via Claude.

The LLM returns a full ``CVContent`` with the same structure as the master, but
only its rewritten summary, bullet wording, and skill ordering are trusted. All
immutable facts (name, contacts, employers, roles, dates, institutions, skills)
are copied back from the master by ``enforce_invariants`` so tailoring can neither
alter nor fabricate them — the model rephrases and reprioritizes, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from .content import CVContent, EducationEntry, ExperienceEntry, SkillRow

_SYSTEM = """You tailor a candidate's CV to a specific job by rephrasing and \
reprioritising existing content. You are given the master CV as JSON and a job \
posting. Return a CV with the EXACT SAME STRUCTURE — same sections, same number of \
education/certification/experience entries, in the same order.

You MAY:
- Rewrite the professional summary to foreground experience relevant to this job.
- Rephrase experience/project bullet points to emphasise relevant skills and impact,
  keeping the same underlying facts and roughly the same number of bullets.
- Reorder the skill categories so the most relevant appear first.

You MUST NOT:
- Invent or exaggerate. Never add employers, roles, dates, qualifications, metrics,
  technologies, or achievements that are not in the master CV.
- Change any employer name, job title, date range, institution, degree, or the
  candidate's name and contact details.
- Add or remove sections or entries.

Keep the candidate honest and the tone professional. Rephrase truthfully."""


@dataclass
class TailorResult:
    tailored: CVContent
    warnings: list[str] = field(default_factory=list)


def _user_prompt(master: CVContent, *, title: str, company: str, description: str) -> str:
    return (
        f"JOB TITLE: {title}\n"
        f"COMPANY: {company}\n\n"
        f"JOB DESCRIPTION:\n{description.strip()}\n\n"
        f"MASTER CV (JSON):\n{master.to_json()}\n\n"
        "Return the tailored CV with the same structure."
    )


def _norm_key(text: str) -> str:
    return " ".join(text.lower().split())


def _align_entries(master_entries, proposed_entries, key_attr: str, section: str, warnings):
    """Pair each master entry with its proposed counterpart, or None if unmatched.

    Matches by the entry's identifying key (employer / institution / cert title),
    NOT by list position: the model sometimes returns entries reordered despite
    instructions, and positional pairing would attach rewritten bullets to the
    wrong entry. Entries whose key the model rewrote fall back to position (only
    safe when the counts line up); anything still unmatched keeps the master.
    """
    remaining = list(proposed_entries)
    aligned = [None] * len(master_entries)
    for i, m in enumerate(master_entries):
        key = _norm_key(getattr(m, key_attr))
        for j, p in enumerate(remaining):
            if _norm_key(getattr(p, key_attr)) == key:
                aligned[i] = remaining.pop(j)
                break
    if any(
        a is not None and (i >= len(proposed_entries) or a is not proposed_entries[i])
        for i, a in enumerate(aligned)
    ):
        warnings.append(f"{section} entries returned out of order; realigned to master")
    if remaining and len(proposed_entries) == len(master_entries):
        leftovers = iter(remaining)
        aligned = [a if a is not None else next(leftovers) for a in aligned]
    elif None in aligned:
        warnings.append(f"{section} entries changed; kept master where unmatched")
    return aligned


def enforce_invariants(master: CVContent, proposed: CVContent) -> TailorResult:
    """Rebuild a safe CV from the master's facts + the proposal's rewritten text."""
    warnings: list[str] = []

    def _bullets(section: str, m: list[str], p: list[str]) -> list[str]:
        # Accept rewritten bullets; only flag if the count changed materially.
        if len(p) != len(m):
            warnings.append(f"{section}: bullet count changed {len(m)} -> {len(p)}")
        return p or m

    # Education: keep facts (institution/dates/degree/modules); take rewritten projects.
    education: list[EducationEntry] = []
    for m, p in zip(
        master.education,
        _align_entries(master.education, proposed.education, "institution", "education", warnings),
    ):
        if p is None:
            education.append(m)
        else:
            education.append(
                m.model_copy(update={"projects": _bullets(m.institution, m.projects, p.projects)})
            )

    # Certifications: keep title/date; take rewritten bullets.
    certifications = [
        m if p is None else m.model_copy(update={"bullets": _bullets(m.title, m.bullets, p.bullets)})
        for m, p in zip(
            master.certifications,
            _align_entries(
                master.certifications, proposed.certifications, "title", "certification", warnings
            ),
        )
    ]

    # Experience: keep organization/role/dates; take rewritten bullets.
    experience: list[ExperienceEntry] = []
    for m, p in zip(
        master.experience,
        _align_entries(
            master.experience, proposed.experience, "organization", "experience", warnings
        ),
    ):
        if p is None:
            experience.append(m)
        else:
            experience.append(
                m.model_copy(update={"bullets": _bullets(m.organization, m.bullets, p.bullets)})
            )

    # Skills: allow reordering only. Reorder master rows by the proposed category
    # order; ignore any rewritten items so no skill can be invented.
    skills = _reorder_skills(master.skills, proposed.skills, warnings)

    safe = CVContent(
        name=master.name,
        contact_lines=list(master.contact_lines),
        summary=proposed.summary.strip() or master.summary,
        education=education,
        certifications=certifications,
        skills=skills,
        experience=experience,
    )
    return TailorResult(tailored=safe, warnings=warnings)


def _reorder_skills(
    master_skills: list[SkillRow], proposed_skills: list[SkillRow], warnings: list[str]
) -> list[SkillRow]:
    by_category = {s.category: s for s in master_skills}
    ordered: list[SkillRow] = []
    seen: set[str] = set()
    for s in proposed_skills:
        row = by_category.get(s.category)
        if row is not None and s.category not in seen:
            ordered.append(row)  # master row verbatim — items are never rewritten
            seen.add(s.category)
    # Append any master categories the proposal dropped, preserving the master.
    missing = [s for s in master_skills if s.category not in seen]
    if len(ordered) != len(master_skills) or any(
        s.category not in by_category for s in proposed_skills
    ):
        warnings.append("skill categories changed; preserved all master skills")
    return ordered + missing


def tailor_cv(
    master: CVContent,
    *,
    title: str,
    company: str,
    description: str,
    client=None,
    model: str | None = None,
) -> TailorResult:
    """Tailor `master` for a job. `client` is an Anthropic-like client (injectable)."""
    if client is None:
        import anthropic

        # Prefer the key from settings/.env; fall back to the SDK's env lookup.
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)

    response = client.messages.parse(
        model=model or settings.anthropic_model,
        max_tokens=4096,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _user_prompt(
                    master, title=title, company=company, description=description
                ),
            }
        ],
        output_format=CVContent,
    )
    return enforce_invariants(master, response.parsed_output)
