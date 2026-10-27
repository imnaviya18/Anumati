export const workspaceLinks = [
  ["/institution", "Institution", ["INSTITUTION_USER"]],
  [
    "/officer",
    "Officer / Committee",
    [
      "SCRUTINY_MEMBER",
      "EVC_MEMBER",
      "REGIONAL_OFFICER",
      "BUREAU_OFFICER",
      "COMMITTEE_MEMBER",
      "COMPETENT_AUTHORITY",
    ],
  ],
  [
    "/oversight",
    "Oversight / Audit",
    [
      "OVERSIGHT_AUDITOR",
      "COMPETENT_AUTHORITY",
      "REGIONAL_OFFICER",
      "BUREAU_OFFICER",
    ],
  ],
  ["/policy", "Policy Governance", ["POLICY_ADMIN", "COMPETENT_AUTHORITY"]],
  ["/admin", "Administration", ["TECHNICAL_ADMIN"]],
];

export function canOpenWorkspace(user, path) {
  return workspaceLinks.some(
    ([url, , roles]) =>
      url === path && user?.roles?.some((role) => roles.includes(role)),
  );
}
