"""Text helpers and the layered HTML/JSON extraction strategies."""

from carfinder.sources import common

# --------------------------------------------------------------- text utils


class TestTextParsers:
    def test_price_basic(self):
        assert common.parse_price("$72,990") == 72990
        assert common.parse_price("$ 54,990 Drive Away") == 54990
        assert common.parse_price("72,990") == 72990

    def test_price_rejects_poa_and_junk(self):
        assert common.parse_price("POA") is None
        assert common.parse_price("Contact dealer") is None
        assert common.parse_price(None) is None
        assert common.parse_price("$99") is None          # too cheap to be a car
        assert common.parse_price("$9,999,999") is None   # sanity cap

    def test_km(self):
        assert common.parse_km("31,500 km") == 31500
        assert common.parse_km("12345km") == 12345
        assert common.parse_km("15 KM") == 15
        assert common.parse_km("no reading") is None

    def test_year(self):
        assert common.parse_year("2022 Kia EV6") == 2022
        assert common.parse_year("MY25 build 2025") == 2025
        assert common.parse_year("call 0412 345 678") is None

    def test_condition(self):
        assert common.infer_condition("Ex-demo, save thousands") == "demo"
        assert common.infer_condition("Brand new in stock now") == "new"
        assert common.infer_condition("Quality used vehicle") == "used"
        assert common.infer_condition("just a title") is None

    def test_location_extraction(self):
        assert common.extract_location_au(
            "2022 Kia EV6 $61,990 31,500 km Trinity Beach, QLD 4879 dealer ad"
        ) == "Trinity Beach, QLD 4879"
        assert common.extract_location_au("Dealer: Cairns QLD") == "Cairns, QLD"
        assert common.extract_location_au("no location in here") is None


# ----------------------------------------------------------------- JSON-LD

JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{
 "@context": "https://schema.org",
 "@type": "ItemList",
 "itemListElement": [
  {"@type": "ListItem", "position": 1, "item": {
     "@type": "Car",
     "name": "2023 Kia EV6 GT-Line",
     "url": "/cars/details/2023-kia-ev6/SSE-AD-14411553/",
     "mileageFromOdometer": {"@type": "QuantitativeValue", "value": "18000"},
     "offers": {"@type": "Offer", "price": "66990",
                "itemCondition": "https://schema.org/UsedCondition",
                "seller": {"@type": "AutoDealer",
                           "address": {"@type": "PostalAddress",
                                       "addressLocality": "Cairns",
                                       "addressRegion": "QLD",
                                       "postalCode": "4870"}}}}}
 ]
}
</script></head><body></body></html>
"""


class TestJsonLd:
    def test_extract_vehicle(self):
        soup = common.soup_of(JSONLD_PAGE)
        vehicles = common.extract_jsonld_vehicles(soup)
        assert len(vehicles) == 1
        raw = common.jsonld_to_raw(vehicles[0], "https://www.carsales.com.au/cars/kia/ev6/")
        assert raw["title"] == "2023 Kia EV6 GT-Line"
        assert raw["price"] == 66990
        assert raw["odometer_km"] == 18000
        assert raw["url"].startswith("https://www.carsales.com.au/cars/details/")
        assert "Cairns" in raw["location"]
        assert raw["condition"] == "used"
        assert raw["year"] == 2023


# -------------------------------------------------------------- __NEXT_DATA__

NEXT_PAGE = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"searchResults":{"items":[
  {"title":"2025 BYD Sealion 7 Premium","detailsUrl":"/for-sale/byd-sealion-7/OAG-AD-987654",
   "adId":"OAG-AD-987654","price":54990,
   "location":{"suburb":"Portsmith","state":"QLD","postcode":"4870"},
   "odometer":"25 km","badge":"Premium"},
  {"title":"2024 BYD Sealion 6 Essential","detailsUrl":"/for-sale/byd-sealion-6/OAG-AD-111111",
   "adId":"OAG-AD-111111","price":39990,
   "location":{"suburb":"Brisbane","state":"QLD"}}
]}}}}
</script></body></html>
"""


class TestNextData:
    def test_walk_finds_listings(self):
        data = common.extract_next_data(NEXT_PAGE)
        assert data is not None
        raws = common.walk_for_listings(data, "https://www.autotrader.com.au/")
        titles = {r["title"] for r in raws}
        assert "2025 BYD Sealion 7 Premium" in titles
        premium = next(r for r in raws if "Premium" in r["title"])
        assert premium["price"] == 54990
        assert premium["source_id"] == "OAG-AD-987654"
        assert "Portsmith" in premium["location"]
        assert premium["odometer_km"] == 25
        assert premium["variant"] == "Premium"
        assert premium["url"].startswith("https://www.autotrader.com.au/for-sale/")


SPLIT_FIELDS_PAGE = """
<html><body>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"results":[
  {"makeName":"Subaru","modelName":"Solterra","variantName":"Touring",
   "buildYear":2026,"price":69990,"url":"/cars-for-sale/car/abc-123456",
   "dealerLocation":"Cairns QLD"}
]}}
</script></body></html>
"""


class TestSynthesizedTitles:
    def test_split_make_model_fields_become_title(self):
        data = common.extract_next_data(SPLIT_FIELDS_PAGE)
        raws = common.walk_for_listings(data, "https://www.drive.com.au/")
        assert len(raws) == 1
        assert raws[0]["title"] == "2026 Subaru Solterra Touring"
        assert raws[0]["price"] == 69990
        assert raws[0]["location"] == "Cairns QLD"

    def test_nested_name_dicts(self):
        node = {"make": {"name": "BYD"}, "model": {"name": "Sealion 7"},
                "badge": "Premium", "year": "2025", "price": 54990,
                "url": "/x/999999"}
        raws = common.walk_for_listings(node, "https://example.com/")
        assert raws and raws[0]["title"] == "2025 BYD Sealion 7 Premium"


# ------------------------------------------------------------ embedded JSON


class TestEmbeddedJson:
    def test_balanced_extraction(self):
        html = ('<script>window.APP_DATA = {"a": {"b": "va}lue", "c": 1}, '
                '"d": [1,2]};</script>')
        data = common.extract_embedded_json(html, [r"window\.APP_DATA\s*="])
        assert data == {"a": {"b": "va}lue", "c": 1}, "d": [1, 2]}

    def test_missing_returns_none(self):
        assert common.extract_embedded_json("<html></html>",
                                            [r"window\.APP_DATA\s*="]) is None


# ---------------------------------------------------------- drive discovery


class TestDriveDiscovery:
    def test_search_paths_from_html_and_json(self):
        from carfinder.sources.drive import Drive
        html = ('<a href="/cars-for-sale/search/qld/">QLD</a>'
                '{"link":"\\/cars-for-sale\\/search\\/qld\\/kia\\/"}'
                '<a href="/cars-for-sale/search/qld/kia/ev6/">EV6</a>')
        paths = Drive._search_paths(html)
        assert "/cars-for-sale/search/qld/" in paths
        assert "/cars-for-sale/search/qld/kia/" in paths      # from escaped JSON
        assert "/cars-for-sale/search/qld/kia/ev6/" in paths

    def test_pick_model_over_make(self):
        from carfinder.sources.drive import Drive
        d = Drive()
        paths = ["/cars-for-sale/search/qld/",
                 "/cars-for-sale/search/qld/kia/",
                 "/cars-for-sale/search/qld/kia/ev6/",
                 "/cars-for-sale/search/qld/kia/ev6/used/"]
        model_url, make_url = d._pick_filter_url(paths, "kia", ["ev6"])
        assert model_url == "/cars-for-sale/search/qld/kia/ev6/"
        assert make_url == "/cars-for-sale/search/qld/kia/"

    def test_sealion7_not_confused_with_sealion6(self):
        from carfinder.sources.drive import Drive
        d = Drive()
        paths = ["/cars-for-sale/search/qld/byd/sealion-6/",
                 "/cars-for-sale/search/qld/byd/sealion-7/"]
        model_url, _ = d._pick_filter_url(
            paths, "byd", ["sealion-7", "sealion7", "sea-lion-7", "sealion"])
        assert model_url == "/cars-for-sale/search/qld/byd/sealion-7/"

    def test_make_only_when_no_model_link(self):
        from carfinder.sources.drive import Drive
        d = Drive()
        paths = ["/cars-for-sale/search/qld/", "/cars-for-sale/search/qld/subaru/"]
        model_url, make_url = d._pick_filter_url(paths, "subaru", ["solterra"])
        assert model_url is None
        assert make_url == "/cars-for-sale/search/qld/subaru/"


# --------------------------------------------------------------- HTML cards

CARDS_PAGE = """
<html><body>
<div class="results">
  <div class="listing-card">
    <h3><a href="/s-ad/edmonton/cars-vans-utes/2022-kia-ev6-gt-line-awd/1330011223">
        2022 Kia EV6 GT-Line AWD</a></h3>
    <span class="price">$61,990</span>
    <span class="odo">31,500 km</span>
    <span class="loc">Edmonton, QLD</span>
  </div>
  <div class="listing-card">
    <h3><a href="/s-ad/brisbane-city/cars-vans-utes/2023-kia-ev6-air/1330099887">
        2023 Kia EV6 Air</a></h3>
    <span class="price">$55,000</span>
    <span class="odo">9,000 km</span>
    <span class="loc">Brisbane City, QLD</span>
  </div>
  <a href="/s-ad/edmonton/cars-vans-utes/2022-kia-ev6-gt-line-awd/1330011223">duplicate link</a>
  <a href="/some-other-page">not a listing</a>
</div>
</body></html>
"""


class TestHarvestCards:
    def test_harvest(self):
        soup = common.soup_of(CARDS_PAGE)
        cards = common.harvest_cards(soup, r"/s-ad/", "https://www.gumtree.com.au/")
        assert len(cards) == 2  # deduped by URL, non-matching anchor ignored
        first = next(c for c in cards if "GT-Line" in c["title"])
        assert first["price"] == 61990
        assert first["odometer_km"] == 31500
        assert first["year"] == 2022
        assert first["url"] == ("https://www.gumtree.com.au/s-ad/edmonton/"
                                "cars-vans-utes/2022-kia-ev6-gt-line-awd/1330011223")
