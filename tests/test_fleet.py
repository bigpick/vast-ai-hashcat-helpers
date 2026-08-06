from remote_hashcat.core.fleet import FleetInstance, FleetRegistry


def test_index_assignment_and_roundtrip(tmp_path):
    reg = FleetRegistry(path=tmp_path / "fleet.json")
    assert reg.list() == []
    assert reg.next_index() == 1

    reg.upsert(FleetInstance(index=1, vast_instance_id=111, gpu_name="RTX_5090", num_gpus=8))
    assert reg.next_index() == 2
    reg.upsert(FleetInstance(index=2, vast_instance_id=222))

    got = reg.get(1)
    assert got is not None
    assert got.vast_instance_id == 111
    assert got.num_gpus == 8
    assert [i.index for i in reg.list()] == [1, 2]


def test_remove_frees_lowest_index(tmp_path):
    reg = FleetRegistry(path=tmp_path / "fleet.json")
    reg.upsert(FleetInstance(index=1, vast_instance_id=111))
    reg.upsert(FleetInstance(index=2, vast_instance_id=222))
    reg.remove(1)
    assert reg.get(1) is None
    assert reg.next_index() == 1


def test_persistence_across_registry_objects(tmp_path):
    path = tmp_path / "fleet.json"
    FleetRegistry(path=path).upsert(FleetInstance(index=1, vast_instance_id=999))
    reloaded = FleetRegistry(path=path).get(1)
    assert reloaded is not None
    assert reloaded.vast_instance_id == 999
