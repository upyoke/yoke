# Audiences and shared posts

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Sessions](index.md) > Audiences and shared posts
<!-- /yoke:breadcrumbs -->

An audience names who receives something. Its rules can name a person, an
organization, an organization role, a project, or a project role. Matching any
rule includes a person. Membership follows current role grants: joining a role
reveals open work; leaving it removes that work and the right to answer it.
An audience grants no action by itself. Decision requests keep their own
approval policy: any needs one answer; all needs an answer for each addressed
role or person. Operator questions keep their own answers and history.

Named audiences can be reused within their owning project. Inline audiences
belong to one use and stay out of named lists. List or create a named audience:

```text
yoke audiences list --project-id 10
yoke audiences create --project-id 10 --name Reviewers --rules '[{"scope_kind":"project","scope_id":10,"role_name":"owner"}]'
```

A post is durable shared work addressed to an audience. Its title, body,
source label and optional key/value fields appear under **Posts** in the web
Inbox and in `yoke inbox list`. It does not expire. Posting requires the
project's `items.write` permission; being addressed does not grant that
permission. Current audience members with project read access can mark it
**Done** for everyone. The record keeps the first person's name and time;
repeating Done reports that same completion.

```text
yoke inbox posts create --project-id 10 --title 'Review this request' --body 'Details to review' --source 'External form' --audience-name Reviewers
yoke inbox posts done 7
```

Other systems use the typed functions `audiences.create`, `audiences.list`,
`inbox.posts.create` and `inbox.posts.done`. Unknown or empty audiences and
missing posting permission refuse with a named reason and a recovery step.
An audience with rules may have no members today; future role members still
see its open posts. Fleet messages remain individual deliveries with a 24-hour
expiry. Delivery notices report results and use **Dismiss**; posts ask for
shared work and use **Done**.

## Related

- [Inbox and messaging](inbox.md)
