# Contribution rules

- All changes must be backward compatible with existing supported behavior, APIs, URLs, configuration, and stored data. Existing installations must continue to work after an upgrade without manual repairs.
- Prefer additive changes and compatible defaults. Preserve existing callers and formats when adding or replacing functionality; do not remove or rename public interfaces or configuration without a compatible fallback.
- Database and storage changes must preserve existing data and include any necessary automatic migrations. Continue to read existing saved content and formats.
- Before committing, check the affected compatibility boundaries and run relevant regression checks against existing behavior and data. Add regression coverage when a change could break an existing contract or upgrade path.
- If a requested change cannot be made backward compatible, explain the incompatibility and obtain explicit user approval before implementing the breaking change; document the migration path.
- Create a Git commit after each completed logical change requested by the user, before handing the task back. A change may span multiple files; do not commit each individual file edit.
- For requests containing independent changes, commit each change separately with a concise, descriptive message explaining the resulting behavior.
- Run checks appropriate to the change before committing. If a check cannot run, report the limitation in the final response and in the commit body; do not claim it passed.
- Inspect the diff and stage only files or hunks belonging to the current change. Preserve unrelated user work and never include secrets or credentials.
- Commit locally without asking for confirmation. Do not push commits unless the user requests it.
- Do not amend existing commits or rewrite history unless requested.
- Include the commit hash and a brief validation result in the final response. If committing fails, explain the failure and preserve the work.
