"""Unit tests for discovery.py: the local-network spoke scanner. Patches discovery._probe
-- the one seam that actually touches the network -- rather than faking the transport, the
same approach test_spokes.py already uses for SpokeGroup._open_and_call."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from hamilton_venus_mcp_hub import discovery
from hamilton_venus_mcp_hub.discovery import DiscoveredSpoke


class ParsePortsTests(unittest.TestCase):
    def test_single_range(self):
        self.assertEqual(discovery.parse_ports("8000-8003"), [8000, 8001, 8002, 8003])

    def test_csv(self):
        self.assertEqual(discovery.parse_ports("8000,9000"), [8000, 9000])

    def test_mixed_and_deduped(self):
        self.assertEqual(discovery.parse_ports("8000-8002,8001,9000"), [8000, 8001, 8002, 9000])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            discovery.parse_ports("")

    def test_bad_range_raises(self):
        with self.assertRaises(ValueError):
            discovery.parse_ports("9000-8000")


class CandidateTargetsTests(unittest.TestCase):
    def test_local_hosts_get_the_full_port_list_others_get_only_the_first(self):
        with patch.object(discovery, "local_ip", return_value="192.168.1.50"), patch.dict(
            os.environ, {discovery.PORTS_ENV: "8000-8002"}
        ):
            targets = discovery.candidate_targets(prefix=24)

        by_host = dict(targets)
        self.assertEqual(by_host["127.0.0.1"], [8000, 8001, 8002])
        self.assertEqual(by_host["192.168.1.50"], [8000, 8001, 8002])
        # Some other host in the same /24 is present, but only on the first port.
        other_hosts = [h for h in by_host if h not in ("127.0.0.1", "192.168.1.50")]
        self.assertTrue(other_hosts)
        self.assertEqual(by_host[other_hosts[0]], [8000])


class ScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_responses_are_returned(self):
        async def fake_probe(client, host, port, timeout_s):
            if (host, port) == ("127.0.0.1", 8000):
                return DiscoveredSpoke(url="http://127.0.0.1:8000/mcp", name="star1")
            return None

        with patch.object(discovery, "_probe", side_effect=fake_probe), patch.object(
            discovery, "candidate_targets", return_value=[("127.0.0.1", [8000, 8001])]
        ):
            found = await discovery.scan()

        self.assertEqual(found, [DiscoveredSpoke(url="http://127.0.0.1:8000/mcp", name="star1")])

    async def test_no_matches_returns_empty_list(self):
        with patch.object(discovery, "_probe", AsyncMock(return_value=None)), patch.object(
            discovery, "candidate_targets", return_value=[("127.0.0.1", [8000])]
        ):
            found = await discovery.scan()

        self.assertEqual(found, [])

    async def test_duplicate_urls_are_deduped(self):
        same = DiscoveredSpoke(url="http://127.0.0.1:8000/mcp", name="star1")

        async def fake_probe(client, host, port, timeout_s):
            return same

        with patch.object(discovery, "_probe", side_effect=fake_probe), patch.object(
            discovery, "candidate_targets", return_value=[("127.0.0.1", [8000]), ("127.0.0.1", [8000])]
        ):
            found = await discovery.scan()

        self.assertEqual(found, [same])


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_service_field_is_rejected(self):
        import httpx

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"service": "something-else", "name": "x"}

        class _FakeClient:
            async def get(self, url, timeout):
                return _FakeResponse()

        result = await discovery._probe(_FakeClient(), "127.0.0.1", 8000, 1.0)
        self.assertIsNone(result)

    async def test_connection_failure_is_treated_as_not_a_spoke(self):
        class _FailingClient:
            async def get(self, url, timeout):
                raise ConnectionRefusedError()

        result = await discovery._probe(_FailingClient(), "127.0.0.1", 8000, 1.0)
        self.assertIsNone(result)

    async def test_matching_response_returns_a_discovered_spoke(self):
        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"service": "hamilton-venus-mcp", "name": "star1"}

        class _FakeClient:
            async def get(self, url, timeout):
                return _FakeResponse()

        result = await discovery._probe(_FakeClient(), "192.168.1.5", 8000, 1.0)
        self.assertEqual(result, DiscoveredSpoke(url="http://192.168.1.5:8000/mcp", name="star1"))


if __name__ == "__main__":
    unittest.main()
