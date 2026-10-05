// Commits the release carries without a backlog item, grouped by project.
import { el } from "./universe_view_support.js";

export function outsideCommitGroups(row) {
  const carried = row.carried_work || {};
  return [carried, ...(carried.bound_projects || [])]
    .filter((project) => (project.commits || []).length)
    .map((project) => ({
      project: project.project || row.project || "Run project",
      commits: project.commits.map((sha) => ({
        sha: String(sha),
        subject: project.commit_subjects?.[sha] || "Subject unavailable",
        author: project.commit_authors?.[sha] || "Author unavailable",
      })),
    }));
}

export function outsideCommitCount(row) {
  return outsideCommitGroups(row).reduce((count, group) => count + group.commits.length, 0);
}

export function appendOutsideCommits(documentNode, host, row) {
  const groups = outsideCommitGroups(row);
  const count = groups.reduce((total, group) => total + group.commits.length, 0);
  if (!count) return;
  const disclosure = el(documentNode, "details", "outside-commits");
  disclosure.appendChild(el(
    documentNode, "summary", "outside-commits-summary",
    `Also includes ${count} commits made outside Yoke`,
  ));
  for (const group of groups) {
    const project = el(documentNode, "div", "outside-commits-project");
    project.appendChild(el(documentNode, "strong", "outside-commits-project-name", group.project));
    const list = el(documentNode, "ul", "outside-commits-list");
    for (const commit of group.commits) {
      const entry = el(documentNode, "li", "outside-commit");
      entry.appendChild(el(documentNode, "code", "mono", commit.sha.slice(0, 12)));
      entry.appendChild(el(documentNode, "span", "outside-commit-subject", commit.subject));
      entry.appendChild(el(documentNode, "span", "outside-commit-author", commit.author));
      list.appendChild(entry);
    }
    project.appendChild(list);
    disclosure.appendChild(project);
  }
  host.appendChild(disclosure);
}
