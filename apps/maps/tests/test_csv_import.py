from django.test import SimpleTestCase

from apps.maps.csv_import import csv_bytes_to_features


class CsvImportTests(SimpleTestCase):
    def test_point_rows(self):
        content = b"name,latitude,longitude,region\nSite A,-6.1,34.9,Manyara\n"
        features = csv_bytes_to_features(content)
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["geometry"]["type"], "Point")
        self.assertEqual(features[0]["geometry"]["coordinates"], [34.9, -6.1])
        self.assertEqual(features[0]["properties"]["name"], "Site A")
        self.assertEqual(features[0]["properties"]["region"], "Manyara")

    def test_grouped_line_vertices(self):
        content = (
            b"feature_id,latitude,longitude\n"
            b"1,-6.1,34.9\n"
            b"1,-6.2,35.0\n"
        )
        features = csv_bytes_to_features(content)
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["geometry"]["type"], "LineString")
        self.assertEqual(
            features[0]["geometry"]["coordinates"],
            [[34.9, -6.1], [35.0, -6.2]],
        )

    def test_wkt_column(self):
        content = b"name,wkt\nRoad,LINESTRING (34.9 -6.1, 35.0 -6.2)\n"
        features = csv_bytes_to_features(content)
        self.assertEqual(features[0]["geometry"]["type"], "LineString")
