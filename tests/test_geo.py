"""Distance resolution: keep the near ones, drop the far ones, flag the rest."""

import pytest

from carfinder import geo


class TestDistances:
    def test_cairns_suburb_is_near_zero(self):
        for loc in ("Cairns, QLD 4870", "Trinity Beach QLD", "Portsmith, QLD",
                    "Smithfield, Queensland 4878", "Edge Hill"):
            d = geo.distance_km(loc)
            assert d is not None and d < 30, loc

    def test_port_douglas_within_radius(self):
        d = geo.distance_km("Port Douglas, QLD 4877")
        assert d is not None and 40 <= d <= 70

    def test_atherton_within_radius(self):
        d = geo.distance_km("Atherton QLD")
        assert d is not None and d <= 100

    def test_townsville_outside_250(self):
        d = geo.distance_km("Townsville, QLD 4810")
        assert d is not None and 250 < d < 330

    def test_brisbane_far(self):
        d = geo.distance_km("Brisbane, QLD")
        assert d is not None and d > 1000

    def test_sydney_very_far(self):
        d = geo.distance_km("Sydney, NSW")
        assert d is not None and d > 1500

    def test_postcode_only_resolution(self):
        # 4870 = Cairns even when the suburb name is unknown to the table.
        d = geo.distance_km("Someweirdsuburb, QLD 4870")
        assert d is not None and d < 30

    def test_unknown_state_only_falls_back_to_capital(self):
        d = geo.distance_km("Randomtown, VIC")
        assert d is not None and d > 2000

    def test_totally_unknown_is_none(self):
        assert geo.distance_km("???") is None
        assert geo.distance_km("") is None
        assert geo.distance_km(None) is None


class TestStateExtraction:
    @pytest.mark.parametrize("text,expected", [
        ("Cairns, QLD 4870", "QLD"),
        ("Somewhere in Queensland", "QLD"),
        ("Melbourne VIC", "VIC"),
        ("New South Wales", "NSW"),
        ("no state here", None),
        (None, None),
    ])
    def test_extract(self, text, expected):
        assert geo.extract_state(text) == expected

    def test_wa_not_extracted_from_random_words(self):
        # "wa" must be a standalone token, not part of "Warwick".
        assert geo.extract_state("Warwick Farm") is None

    def test_multi_state_nav_text_is_ambiguous(self):
        # Nav/footer state lists must not be mistaken for an address.
        assert geo.extract_state("Queensland Western Australia, ACT") is None
        assert geo.extract_state("NSW VIC QLD WA SA TAS") is None
