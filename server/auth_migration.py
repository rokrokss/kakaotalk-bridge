"""Retire upstream identity-provider state without touching passkeys or their grants."""


def retire_social_login(state):
    with state.transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "DELETE FROM records WHERE kind IN ('kakao','kakao-flow','kakao-enroll','google','google-flow')"
        )
        for kind in ("session", "pair", "approval", "code", "grant"):
            for identity, row in state.all(kind, db=db):
                if isinstance(row.get("policy"), str) and row["policy"].startswith(
                    ("kakao:", "google:")
                ):
                    state.delete(kind, identity, db=db)
