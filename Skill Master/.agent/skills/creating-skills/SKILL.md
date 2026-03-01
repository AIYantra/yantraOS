---
name: creating-skills
description: "Generates high-quality, predictable, and efficient .agent/skills/ directories based on user requirements. Use when the user asks to create, build, or generate a new skill, or mentions 'skill creator'."
---

# Antigravity Skill Creator

## When to use this skill
- The user asks to create, build, or generate a new skill
- The user mentions "skill creator" or "create a skill"
- The user wants to scaffold a `.agent/skills/` directory

## Core Structural Requirements

Every skill you generate must follow this folder hierarchy:

```
<skill-name>/
├── SKILL.md          (Required: Main logic and instructions)
├── scripts/          (Optional: Helper scripts)
├── examples/         (Optional: Reference implementations)
└── resources/        (Optional: Templates or assets)
```

## YAML Frontmatter Standards

The `SKILL.md` must start with YAML frontmatter following these strict rules:

- **name**: Gerund form (e.g., `testing-code`, `managing-databases`). Max 64 chars. Lowercase, numbers, and hyphens only. No "claude" or "anthropic" in the name.
- **description**: Written in **third person**. Must include specific triggers/keywords. Max 1024 chars. (e.g., "Extracts text from PDFs. Use when the user mentions document processing or PDF files.")

## Writing Principles (The "Claude Way")

- **Conciseness**: Assume the agent is smart. Do not explain basic concepts. Focus only on the unique logic of the skill.
- **Progressive Disclosure**: Keep `SKILL.md` under 500 lines. If more detail is needed, link to secondary files (e.g., `[See ADVANCED.md](ADVANCED.md)`) only one level deep.
- **Forward Slashes**: Always use `/` for paths, never `\`.
- **Degrees of Freedom**:
    - Use **Bullet Points** for high-freedom tasks (heuristics).
    - Use **Code Blocks** for medium-freedom (templates).
    - Use **Specific Bash Commands** for low-freedom (fragile operations).

## Workflow & Feedback Loops

For complex tasks, include:

1.  **Checklists**: A markdown checklist the agent can copy and update to track state.
2.  **Validation Loops**: A "Plan-Validate-Execute" pattern. (e.g., Run a script to check a config file BEFORE applying changes).
3.  **Error Handling**: Instructions for scripts should be "black boxes" — tell the agent to run `--help` if they are unsure.

## Output Template

When asked to create a skill, output the result in this format:

### [Folder Name]
**Path:** `.agent/skills/[skill-name]/`

### [SKILL.md]

```markdown
---
name: [gerund-name]
description: [3rd-person description]
---

# [Skill Title]

## When to use this skill
- [Trigger 1]
- [Trigger 2]

## Workflow
[Insert checklist or step-by-step guide here]

## Instructions
[Specific logic, code snippets, or rules]

## Resources
- [Link to scripts/ or resources/]
```

### [Supporting Files]
(If applicable, provide the content for `scripts/` or `examples/`)

## Instructions for Use

1.  **Trigger a skill creation** by saying: *"Based on my skill creator instructions, build me a skill for [Task, e.g., 'automating React component testing with Vitest']."*
2.  The agent will generate the full `.agent/skills/` directory structure with all required files.
3.  Review the generated `SKILL.md` to ensure it meets the quality standards above.
