"""Labeled synthetic dataset for the Phase 3 eval harness (SPEC.md §7).

Labeling guide (SPEC.md §5's "definition of a decision", written down here
per the spec's instruction that it doubles as the labeling guide):

A thread is a **decision** only if it contains a durable, resolved statement
about how the team will operate — a technical choice, a policy, a process
change, or a product/scope call. A thread is explicitly **not** a decision if
it is only: an open question, an unresolved proposal, a joke/aside, a status
update, or a *provisional* trial ("let's try X and see how it goes") — the
last one is excluded because it lacks durability, per the spec's call to
settle this up front.
"""

from dataclasses import dataclass, field


@dataclass
class LabeledMessage:
    author_id: str
    content: str
    offset_seconds: int = 0
    is_reply: bool = False
    checkmark_reaction: bool = False


@dataclass
class LabeledThread:
    id: str
    category: str
    is_decision: bool
    messages: list[LabeledMessage] = field(default_factory=list)


DATASET: list[LabeledThread] = [
    # --- Decisions: technical ---
    LabeledThread(
        id="tech-pagination",
        category="technical-decision",
        is_decision=True,
        messages=[
            LabeledMessage("alice", "should we paginate the /users endpoint by offset or cursor?"),
            LabeledMessage(
                "bob", "cursor is better for large tables, offset breaks on inserts", offset_seconds=30
            ),
            LabeledMessage(
                "alice",
                "ok, let's go with cursor-based pagination then",
                offset_seconds=60,
                is_reply=True,
            ),
        ],
    ),
    LabeledThread(
        id="tech-db-choice",
        category="technical-decision",
        is_decision=True,
        messages=[
            LabeledMessage("carol", "postgres or mongo for the new service?"),
            LabeledMessage("dave", "postgres, we already run it and need transactions", offset_seconds=45),
            LabeledMessage("carol", "we decided to use postgres for the database", offset_seconds=90),
        ],
    ),
    LabeledThread(
        id="tech-auth-deprecate",
        category="technical-decision",
        is_decision=True,
        messages=[
            LabeledMessage("erin", "the v1 auth flow keeps causing support tickets"),
            LabeledMessage("frank", "yeah it's not worth maintaining anymore", offset_seconds=40),
            LabeledMessage("erin", "final call: we're deprecating the v1 auth flow", offset_seconds=80),
        ],
    ),
    LabeledThread(
        id="tech-checkmark",
        category="technical-decision",
        is_decision=True,
        messages=[
            LabeledMessage("grace", "should the worker poll every 30s or 60s?"),
            LabeledMessage(
                "heidi",
                "60s is fine, nothing here is that time sensitive",
                offset_seconds=35,
                checkmark_reaction=True,
            ),
        ],
    ),
    # --- Decisions: policy ---
    LabeledThread(
        id="policy-pr-approvals",
        category="policy-decision",
        is_decision=True,
        messages=[
            LabeledMessage("ivan", "one reviewer isn't catching enough bugs before merge"),
            LabeledMessage(
                "judy", "the policy is that all PRs require two approvals before merge", offset_seconds=50
            ),
        ],
    ),
    LabeledThread(
        id="policy-oncall-rotation",
        category="policy-decision",
        is_decision=True,
        messages=[
            LabeledMessage("kim", "from now on, oncall rotates every monday instead of every two weeks"),
            LabeledMessage("liam", "sounds good, easier to plan around", offset_seconds=25),
        ],
    ),
    LabeledThread(
        id="policy-response-format",
        category="policy-decision",
        is_decision=True,
        messages=[
            LabeledMessage("mia", "customers keep asking for consistent error shapes"),
            LabeledMessage(
                "noah", "from now on, all API responses must be paginated by default", offset_seconds=40
            ),
            LabeledMessage("mia", "agreed, that'll fix the mobile timeout issue too", offset_seconds=70),
        ],
    ),
    # --- Decisions: process ---
    LabeledThread(
        id="process-standup-time",
        category="process-decision",
        is_decision=True,
        messages=[
            LabeledMessage("olga", "half the team is late to the 9am standup"),
            LabeledMessage("paul", "let's go with 9:30 instead", offset_seconds=30),
            LabeledMessage("olga", "works for me, moving it", offset_seconds=55),
        ],
    ),
    LabeledThread(
        id="process-release-cadence",
        category="process-decision",
        is_decision=True,
        messages=[
            LabeledMessage("quinn", "weekly releases are too risky with the current test coverage"),
            LabeledMessage(
                "rosa",
                "we've decided to move to biweekly releases until coverage improves",
                offset_seconds=45,
            ),
        ],
    ),
    # --- Decisions: product ---
    LabeledThread(
        id="product-scope-cut",
        category="product-decision",
        is_decision=True,
        messages=[
            LabeledMessage("sam", "we're not going to hit the deadline with csv export included"),
            LabeledMessage("tara", "we're going to cut csv export from this release then", offset_seconds=35),
            LabeledMessage("sam", "yeah, push it to next quarter", offset_seconds=60),
        ],
    ),
    LabeledThread(
        id="product-pricing-tier",
        category="product-decision",
        is_decision=True,
        messages=[
            LabeledMessage("uma", "should the free tier include the export feature or not"),
            LabeledMessage(
                "victor",
                "final decision: free tier stays read-only, export is pro-only",
                offset_seconds=50,
            ),
        ],
    ),
    # --- Not-decisions: open questions ---
    LabeledThread(
        id="question-unresolved-timezone",
        category="open-question",
        is_decision=False,
        messages=[
            LabeledMessage("walt", "should we store timestamps in utc or local time?"),
            LabeledMessage(
                "xena", "good question, let me check what the mobile team assumes", offset_seconds=30
            ),
        ],
    ),
    LabeledThread(
        id="question-vendor-choice",
        category="open-question",
        is_decision=False,
        messages=[
            LabeledMessage("yara", "anyone looked into alternatives to our current email provider?"),
            LabeledMessage("zack", "not yet, been meaning to", offset_seconds=20),
        ],
    ),
    # --- Not-decisions: unresolved proposals ---
    LabeledThread(
        id="proposal-unresolved-cache",
        category="unresolved-proposal",
        is_decision=False,
        messages=[
            LabeledMessage("amir", "what if we added a redis cache in front of the search index"),
            LabeledMessage(
                "bella", "could help, but let's see how bad the load actually gets first", offset_seconds=40
            ),
        ],
    ),
    LabeledThread(
        id="proposal-unresolved-rewrite",
        category="unresolved-proposal",
        is_decision=False,
        messages=[
            LabeledMessage("caleb", "we could rewrite the ingestion service in rust for speed"),
            LabeledMessage(
                "dana",
                "that's a big lift, would need more data on where time actually goes",
                offset_seconds=45,
            ),
        ],
    ),
    # --- Not-decisions: provisional / trial ---
    LabeledThread(
        id="provisional-trial-model",
        category="provisional",
        is_decision=False,
        messages=[
            LabeledMessage("edwin", "let's try the smaller embedding model for a week and see how it does"),
            LabeledMessage("fatima", "ok, i'll keep an eye on the candidate quality", offset_seconds=30),
        ],
    ),
    LabeledThread(
        id="provisional-trial-schedule",
        category="provisional",
        is_decision=False,
        messages=[
            LabeledMessage("gabe", "let's try async standups for a couple weeks and see if it works"),
            LabeledMessage("hana", "worth a shot, sync ones keep getting skipped anyway", offset_seconds=35),
        ],
    ),
    # --- Not-decisions: jokes / banter ---
    LabeledThread(
        id="joke-standup-banter",
        category="joke",
        is_decision=False,
        messages=[
            LabeledMessage("ian", "final decision: pineapple does not belong on pizza"),
            LabeledMessage("jenna", "lol we are not doing this again", offset_seconds=15),
        ],
    ),
    LabeledThread(
        id="joke-deploy-friday",
        category="joke",
        is_decision=False,
        messages=[
            LabeledMessage("kyle", "who approved a friday deploy again"),
            LabeledMessage(
                "lena", "we've decided that whoever does this owes the team donuts", offset_seconds=20
            ),
        ],
    ),
    # --- Not-decisions: status updates ---
    LabeledThread(
        id="status-deploy-done",
        category="status-update",
        is_decision=False,
        messages=[
            LabeledMessage("mona", "deployed the hotfix to prod, monitoring now"),
            LabeledMessage("nate", "thanks, looks stable so far", offset_seconds=25),
        ],
    ),
    LabeledThread(
        id="status-ticket-progress",
        category="status-update",
        is_decision=False,
        messages=[
            LabeledMessage("omar", "picked up the webhook retry bug, digging into logs now"),
            LabeledMessage("priya", "let me know if you need the staging creds", offset_seconds=30),
        ],
    ),
    LabeledThread(
        id="status-meeting-notes",
        category="status-update",
        is_decision=False,
        messages=[
            LabeledMessage("quincy", "posted the design review notes in the doc"),
            LabeledMessage("rachel", "thanks, will read before tomorrow", offset_seconds=20),
        ],
    ),
    # --- Not-decisions: casual chat with superficially decision-like phrasing ---
    LabeledThread(
        id="casual-lunch-plan",
        category="casual",
        is_decision=False,
        messages=[
            LabeledMessage("steve", "should we get lunch at the new place today"),
            LabeledMessage("tina", "let's go with the taco place instead, closer", offset_seconds=15),
        ],
    ),
    LabeledThread(
        id="casual-desk-plants",
        category="casual",
        is_decision=False,
        messages=[
            LabeledMessage("uma2", "final call: my desk plant is definitely dying"),
            LabeledMessage("victor2", "water it more lol", offset_seconds=10),
        ],
    ),
]


# Thread ids meant to be interleaved into ONE shared channel (Stage 0 stress
# scenario, mirroring this session's edupaid/sentinel manual test) — not part
# of the isolated-channel headline metric.
INTERLEAVED_GROUPS: list[tuple[str, ...]] = [
    ("tech-pagination", "tech-db-choice"),
    ("policy-pr-approvals", "process-standup-time"),
]
