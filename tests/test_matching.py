"""Model-matching regexes: the wrong car must never slip through."""

from carfinder.config import QUERIES_BY_KEY

EV6 = QUERIES_BY_KEY["kia-ev6"]
SEALION = QUERIES_BY_KEY["byd-sealion-7"]
SOLTERRA = QUERIES_BY_KEY["subaru-solterra"]


class TestEV6:
    def test_matches_plain(self):
        assert EV6.matches("2022 Kia EV6 GT-Line")

    def test_matches_spaced_and_hyphen(self):
        assert EV6.matches("Kia EV 6 Air")
        assert EV6.matches("KIA EV-6 GT")

    def test_rejects_siblings(self):
        assert not EV6.matches("2023 Kia EV9 GT-Line")
        assert not EV6.matches("Kia EV5 Earth")
        assert not EV6.matches("2024 Kia Niro EV")

    def test_rejects_ev60(self):
        assert not EV6.matches("LDV eDeliver EV60 van")


class TestSealion7:
    def test_matches(self):
        assert SEALION.matches("2025 BYD Sealion 7 Premium")
        assert SEALION.matches("BYD SEALION 7 PERFORMANCE AWD")
        assert SEALION.matches("BYD Sea Lion 7 Premium")
        assert SEALION.matches("BYD Sealion-7")

    def test_rejects_sealion_6_and_8(self):
        assert not SEALION.matches("2024 BYD Sealion 6 Dynamic")
        assert not SEALION.matches("BYD Sealion 8 Premium")

    def test_rejects_byd_seal(self):
        assert not SEALION.matches("2024 BYD Seal Premium")

    def test_premium_variant_flag(self):
        assert SEALION.variant_matches("Sealion 7 Premium RWD")
        assert not SEALION.variant_matches("Sealion 7 Performance AWD")


class TestSolterra:
    def test_matches_correct_spelling(self):
        assert SOLTERRA.matches("2026 Subaru Solterra AWD")

    def test_matches_common_misspelling(self):
        assert SOLTERRA.matches("Subaru Soltera electric SUV")

    def test_rejects_other_subarus(self):
        assert not SOLTERRA.matches("Subaru Outback Touring")
        assert not SOLTERRA.matches("Subaru Forester Hybrid")
