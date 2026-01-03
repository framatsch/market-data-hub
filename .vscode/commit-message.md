# Commit Message Guidelines

## Format

```
<Short description in one sentence>

- <Detail 1>
- <Detail 2>
- <Detail n>
```

## Rules

1. **Subject Line**: One sentence describing what was done (max 72 characters)
2. **Blank Line**: Always separate subject from details
3. **Details**: Very short, concise bullet points using keywords or brief sentences
4. **Max 5 Details**: Summarize if more changes were made
5. **Language**: English preferred

## Examples

### Good ✅

```
Add Authelia Helm values for SSO authentication

- Configure OIDC provider settings
- Set up Google SSO integration
- Add ingress with TLS on auth.framas.cloud
- Define resource limits (256Mi/512Mi)
```

```
Fix pod crash in monitoring namespace

- Increase memory limit from 256Mi to 512Mi
- Add missing environment variable
- Update liveness probe timeout
```

```
Update multiple Helm values for security hardening

- Enable network policies for all apps
- Add pod security contexts
- Configure read-only root filesystem
- Update resource requests across services
```

### Bad ❌

```
updates
```
→ Too vague, no details

```
Fixed the thing that was broken in the deployment because it wasn't working properly and also updated some other stuff

- Changed line 45 in file helm_values/grafana_values.yaml to have a different value
- Also changed line 46
- And line 47
- Modified line 48 too
- Line 49 was updated
- Don't forget line 50
- Plus lines 51-100
```
→ Subject too long, too many details, not summarized

## Quick Reference

| Element | Guideline |
|---------|-----------|
| Subject | 1 sentence, max 72 chars, imperative mood |
| Details | Max 5 bullet points |
| Detail style | Keywords or short sentence |
| Language | English |
| Blank line | Required between subject and details |

## Imperative Mood Examples

Use imperative mood (like giving a command):

- ✅ "Add feature" not "Added feature"
- ✅ "Fix bug" not "Fixed bug"
- ✅ "Update config" not "Updated config"
- ✅ "Remove deprecated code" not "Removed deprecated code"

## Common Prefixes (Optional)

You may use prefixes for categorization:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `refactor:` Code refactoring
- `chore:` Maintenance tasks
- `config:` Configuration changes

Example with prefix:
```
feat: Add Prometheus alerting rules for disk usage

- Create alert for >80% disk usage
- Add notification to Slack channel
- Configure 5-minute evaluation interval
```
