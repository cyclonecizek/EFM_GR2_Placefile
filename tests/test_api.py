import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ksc_fieldmill_placefile as f

class ApiTests(unittest.TestCase):
    def row(self, **changes):
        r = dict(field_mill=2, reading_date="2026-10-16", reading_time="09:57:00",
                 value=-1200, flag=None, lat=28.68, lon=-80.71)
        r.update(changes)
        return r

    def test_signed_units_time_and_flags(self):
        o = f.parse_api([self.row(value=0, flag="X")])[0]
        self.assertEqual(o.site, "FM02")
        self.assertEqual(o.value_vpm, 0)
        self.assertEqual(o.flag, "X")
        self.assertEqual(o.time, datetime(2026, 10, 16, 9, 57, tzinfo=timezone.utc))
        text = f.build_placefile({o.site: o}, {o.site: (o.latitude,o.longitude)}, o.time)
        self.assertIn("API status flag: X", text)
        self.assertIn("1-min Mean: +0 V/m", text)

    def test_coordinates_and_configured_network(self):
        obs = f.parse_api([self.row(), self.row(field_mill=64, lat=24.32, lon=-82.5)])
        latest = f.latest_by_site(obs)
        sites = f.observation_sites(latest, {"FM02": (28,-80)})
        self.assertEqual(sites, {"FM02": (28.68,-80.71)})
        text = f.build_placefile(latest, sites, obs[0].time)
        self.assertEqual(text.count("Object:"), 1)
        self.assertIn("Absolute EF: 1200", text)
        self.assertEqual(f.category_for(-1200)[2], "RED")

    def test_latest_order_and_missing(self):
        obs = f.parse_api([self.row(), self.row(reading_time="09:56:00", value=12), self.row(value=None)])
        self.assertEqual(len(obs), 2)
        self.assertEqual(f.latest_by_site(obs)["FM02"].value_vpm, -1200)
        for payload in ([], {"error":"failed"}):
            with self.assertRaises(ValueError): f.parse_api(payload)

if __name__ == "__main__": unittest.main()
