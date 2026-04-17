from neuralclaw.swarm.delegation import (
    DelegationChain,
    DelegationContext,
    DelegationRecord,
    DelegationStatus,
)


def test_prune_records_uses_created_at_for_completed_history() -> None:
    chain = DelegationChain()
    chain.MAX_RECORD_HISTORY = 2

    record_a = DelegationRecord(
        id="a",
        parent_id=None,
        agent_name="planner",
        context=DelegationContext(task_description="a"),
        status=DelegationStatus.COMPLETED,
        created_at=10.0,
        completed_at=20.0,
    )
    record_b = DelegationRecord(
        id="b",
        parent_id=None,
        agent_name="builder",
        context=DelegationContext(task_description="b"),
        status=DelegationStatus.FAILED,
        created_at=30.0,
        completed_at=40.0,
    )
    record_c = DelegationRecord(
        id="c",
        parent_id=None,
        agent_name="reviewer",
        context=DelegationContext(task_description="c"),
        status=DelegationStatus.TIMED_OUT,
        created_at=50.0,
        completed_at=60.0,
    )

    chain._records = {record.id: record for record in (record_a, record_b, record_c)}

    chain._prune_records()

    assert len(chain._records) == 2
    assert "a" not in chain._records
    assert set(chain._records.keys()) == {"b", "c"}
