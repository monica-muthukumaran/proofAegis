"""
approval_service.py — who is allowed to approve what, and who is not.

`approved_with_exception` releases money that the deterministic match said was
questionable. Until now any signed-in user could set it on any case at any
value, and the audit trail recorded who did it after the fact. That is a
record of a control failure rather than a control.

Two rules, both standard in accounts payable and both deliberately simple:

  Segregation of duties
      The person who created the case or uploaded its documents cannot be the
      person who approves it. Not because they are suspected of anything —
      because a second pair of eyes is the entire mechanism, and one person
      doing both steps removes it.

  Approval limits
      Authority is banded by value. Someone who can release ₹10,000 is not
      thereby authorised to release ₹10,00,000.

Both are configured in Firestore under settings/approval_policy, so a
workspace can set its own bands without a deploy:

    {
      "segregation_of_duties": true,
      "limits": [
        {"role": "ap_clerk",      "max_value": 50000},
        {"role": "ap_manager",    "max_value": 500000},
        {"role": "controller",    "max_value": null}     // no limit
      ],
      "default_role": "ap_clerk"
    }

A user's role comes from their verified token's custom claims, so it cannot be
set by the client. With no policy configured the behaviour is unchanged, which
keeps the demo flow working: an absent policy is not an implicit denial. Both
rules are opt-in at the WORKSPACE level and default-on within a policy — write
`{"segregation_of_duties": false}` to configure a workspace that wants the
bands without the second pair of eyes.
"""
from __future__ import annotations

from typing import Optional

# Statuses that release or settle money and therefore need authority. The
# other user-settable statuses move a case between queues and do not.
APPROVAL_STATUSES = {"approved_with_exception", "resolved", "closed"}

DEFAULT_POLICY = {
    "segregation_of_duties": True,
    "limits": [],
    "default_role": None,
}


class ApprovalDenied(Exception):
    """Carries an HTTP-ready reason. Raised instead of returning a bare False
    so a caller cannot accidentally ignore the decision."""

    def __init__(self, code: str, detail: str, **context):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.context = context


def _key(value) -> str:
    return str(value or "").strip().lower()


def participants(case: dict, documents: list[dict]) -> set[str]:
    """Everyone who put this case together: its creator and every uploader."""
    people = {_key(case.get("created_by")), _key(case.get("uploaded_by"))}
    for document in documents or []:
        people.add(_key(document.get("uploaded_by")))
    return {person for person in people if person}


def limit_for_role(policy: dict, role: Optional[str]) -> Optional[float]:
    """The value this role may approve. None means no limit.

    A role that appears in no band has no authority at all — that is the safe
    reading of an unlisted role, and it is distinguishable from "no limit"
    because this raises rather than returning None.
    """
    limits = policy.get("limits") or []
    if not limits:
        return None  # No bands configured: unlimited, i.e. unchanged behaviour.

    target = _key(role) or _key(policy.get("default_role"))
    for band in limits:
        if _key(band.get("role")) == target:
            maximum = band.get("max_value")
            return None if maximum is None else float(maximum)

    raise ApprovalDenied(
        "role_not_authorized",
        f"'{role or 'no role'}' is not listed in this workspace's approval policy, so it "
        f"carries no approval authority. Ask an administrator to assign a role.",
        role=role,
    )


def check_approval(new_status: str, *, actor: str, actor_role: Optional[str],
                   case: dict, documents: list[dict], amount: float,
                   policy: Optional[dict] = None) -> None:
    """
    Raises ApprovalDenied when this actor may not set this status.

    Returns None — silently — for every status that does not release money,
    and for every workspace that has not configured a policy.
    """
    if new_status not in APPROVAL_STATUSES:
        return

    # An unconfigured workspace is not an implicit denial. Segregation of
    # duties needs a second reviewer to segregate the work TO, and a workspace
    # that has configured no policy has no roles, no bands and — in the demo
    # and single-user cases — no second person. Applying it there did not
    # protect anything: every case is prepared by whoever is signed in, so
    # every case became permanently unresolvable, with `resolved`, `closed`
    # and `approved_with_exception` all answering 403 forever.
    #
    # The control is unchanged wherever a policy exists: `segregation_of_duties`
    # still defaults to on INSIDE a configured policy, so a workspace that sets
    # only approval bands still gets it.
    if not policy:
        return

    policy = {**DEFAULT_POLICY, **policy}

    if policy.get("segregation_of_duties"):
        involved = participants(case, documents)
        if _key(actor) in involved:
            raise ApprovalDenied(
                "segregation_of_duties",
                f"{actor} prepared this case, so the same person cannot also approve it. "
                f"A second reviewer must take this step.",
                actor=actor,
            )

    limit = limit_for_role(policy, actor_role)
    if limit is not None and amount > limit:
        raise ApprovalDenied(
            "approval_limit_exceeded",
            f"This case carries {amount:,.2f} at risk, above the {limit:,.2f} that "
            f"'{actor_role or policy.get('default_role') or 'this role'}' may approve. "
            f"Escalate it to someone with a higher limit.",
            amount=amount, limit=limit, role=actor_role,
        )
