import pytest

from remote_hashcat.core.config import sanitize
from remote_hashcat.core.provider import VastProvider


class FakeSDK:
    def __init__(self):
        self.created = None

    def search_offers(self, query, order, limit):
        return [{"id": 1, "dph_total": 1.0}]

    def create_instance(self, **kwargs):
        self.created = kwargs
        return {"new_contract": 4242}

    def show_instance(self, id):
        return {"actual_status": "running", "ssh_host": "h", "ssh_port": 22}

    def destroy_instance(self, id):
        pass

    def show_instances(self):
        return [{"id": 1}]


def test_repr_hides_key():
    assert repr(VastProvider(sdk=FakeSDK())) == "VastProvider(...)"


def test_create_instance_passes_only_accepted_kwargs():
    sdk = FakeSDK()
    contract = VastProvider(sdk=sdk).create_instance(
        offer_id=7, image="img", disk=40, label="remote-hashcat"
    )
    assert contract == 4242
    assert sdk.created["id"] == 7
    assert sdk.created["image"] == "img"
    assert sdk.created["disk"] == 40
    assert sdk.created["label"] == "remote-hashcat"
    # ssh/direct are not valid vastai kwargs and must never be sent
    assert "ssh" not in sdk.created and "direct" not in sdk.created


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("VAST_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VAST_API_KEY"):
        VastProvider()


def test_sanitize_redacts_api_key():
    assert "REDACTED" in sanitize("boom api_key=deadbeef0123 more")
    assert "deadbeef0123" not in sanitize("boom api_key=deadbeef0123 more")
